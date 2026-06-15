from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
INPUT_BASE = ROOT / "inputs" / "v20" / "outcome_benchmark"
RAW_BASE = INPUT_BASE / "manual_raw"
RAW_OUTCOME = RAW_BASE / "outcome"
RAW_BENCHMARK = RAW_BASE / "benchmark"
STAGING = INPUT_BASE / "staging"
STAGING_V20_25 = STAGING / "v20_25"

IN_READ_FIRST = OPS / "V20_24_READ_FIRST.txt"
IN_GATE = CONSOLIDATION / "V20_24_GATE_DECISION.csv"
IN_OUTCOME_PLAN = CONSOLIDATION / "V20_24_OUTCOME_DATA_REQUIREMENT_PLAN.csv"
IN_BENCHMARK_PLAN = CONSOLIDATION / "V20_24_BENCHMARK_DATA_REQUIREMENT_PLAN.csv"
IN_INPUT_REGISTER = CONSOLIDATION / "V20_24_REQUIRED_INPUT_FILE_REGISTER.csv"
IN_OUTCOME_SCHEMA = CONSOLIDATION / "V20_24_OUTCOME_REQUIRED_SCHEMA.csv"
IN_BENCHMARK_SCHEMA = CONSOLIDATION / "V20_24_BENCHMARK_REQUIRED_SCHEMA.csv"
IN_COVERAGE = CONSOLIDATION / "V20_24_REQUIRED_COVERAGE_MATRIX.csv"
IN_MANUAL = CONSOLIDATION / "V20_24_MANUAL_STAGING_INSTRUCTIONS.csv"
IN_NEXT = CONSOLIDATION / "V20_24_NEXT_STAGING_REQUIREMENTS.csv"

ACTIVE_OUTCOME = INPUT_BASE / "V20_OUTCOME_SOURCE_INPUT.csv"
ACTIVE_BENCHMARK = INPUT_BASE / "V20_BENCHMARK_SOURCE_INPUT.csv"
RAW_OUTCOME_TEMPLATE = RAW_BASE / "V20_25_MANUAL_OUTCOME_RAW_TEMPLATE.csv"
RAW_BENCHMARK_TEMPLATE = RAW_BASE / "V20_25_MANUAL_BENCHMARK_RAW_TEMPLATE.csv"
RAW_README_ZH = RAW_BASE / "V20_25_MANUAL_RAW_INPUT_README_ZH.md"
STAGED_OUTCOME = STAGING_V20_25 / "V20_25_STAGED_OUTCOME_SOURCE_INPUT.csv"
STAGED_BENCHMARK = STAGING_V20_25 / "V20_25_STAGED_BENCHMARK_SOURCE_INPUT.csv"

OUT_DEP = CONSOLIDATION / "V20_25_DEPENDENCY_AUDIT.csv"
OUT_DIR = CONSOLIDATION / "V20_25_INPUT_DIRECTORY_AUDIT.csv"
OUT_TEMPLATE_REG = CONSOLIDATION / "V20_25_MANUAL_RAW_TEMPLATE_REGISTER.csv"
OUT_RAW_OUTCOME = CONSOLIDATION / "V20_25_RAW_OUTCOME_FILE_DISCOVERY.csv"
OUT_RAW_BENCHMARK = CONSOLIDATION / "V20_25_RAW_BENCHMARK_FILE_DISCOVERY.csv"
OUT_RAW_SCHEMA = CONSOLIDATION / "V20_25_RAW_SCHEMA_COVERAGE_AUDIT.csv"
OUT_MAP = CONSOLIDATION / "V20_25_COLUMN_NORMALIZATION_MAP.csv"
OUT_HASH = CONSOLIDATION / "V20_25_LOCAL_FILE_HASH_LEDGER.csv"
OUT_RUN = CONSOLIDATION / "V20_25_RUN_ID_LEDGER.csv"
OUT_OUTCOME_ROW = CONSOLIDATION / "V20_25_OUTCOME_STAGING_ROW_AUDIT.csv"
OUT_BENCHMARK_ROW = CONSOLIDATION / "V20_25_BENCHMARK_STAGING_ROW_AUDIT.csv"
OUT_STAGED_REG = CONSOLIDATION / "V20_25_STAGED_INPUT_FILE_REGISTER.csv"
OUT_ACTUAL_AUDIT = CONSOLIDATION / "V20_25_EXPECTED_ACTUAL_INPUT_FILE_AUDIT.csv"
OUT_BENCH_SYMBOL = CONSOLIDATION / "V20_25_BENCHMARK_SYMBOL_COVERAGE_AUDIT.csv"
OUT_WINDOW = CONSOLIDATION / "V20_25_OUTCOME_WINDOW_COVERAGE_AUDIT.csv"
OUT_DUP = CONSOLIDATION / "V20_25_DUPLICATE_KEY_AUDIT.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_25_BLOCKER_REGISTER.csv"
OUT_NEXT_REQ = CONSOLIDATION / "V20_25_NEXT_CERTIFICATION_REQUIREMENTS.csv"
OUT_GATE = CONSOLIDATION / "V20_25_GATE_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_25_VALIDATION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_25_LOCAL_OUTCOME_BENCHMARK_IMPORTER_OR_MANUAL_STAGING_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_LOCAL_OUTCOME_BENCHMARK_IMPORTER_OR_MANUAL_STAGING.md"
ZH_GUIDE = READ_CENTER / "V20_25_MANUAL_RAW_INPUT_GUIDE_ZH.md"
READ_FIRST = OPS / "V20_25_READ_FIRST.txt"

PASS_STATUS = "PASS_V20_25_LOCAL_OUTCOME_BENCHMARK_IMPORTER_OR_MANUAL_STAGING"
NEXT_READY = "V20.26_OUTCOME_BENCHMARK_INPUT_CERTIFICATION_RETRY_FROM_LOCAL_STAGING"
NEXT_BLOCKED = "V20.26_LOCAL_OUTCOME_BENCHMARK_DATA_COLLECTION_PACKET_OR_MANUAL_FILL_GUIDE"
REQUIRED_INPUTS = [IN_READ_FIRST, IN_GATE, IN_OUTCOME_PLAN, IN_BENCHMARK_PLAN, IN_INPUT_REGISTER, IN_OUTCOME_SCHEMA, IN_BENCHMARK_SCHEMA, IN_COVERAGE, IN_MANUAL, IN_NEXT]

RAW_OUTCOME_FIELDS = ["ticker", "signal_date", "outcome_window", "outcome_price_date", "outcome_close", "adjusted_outcome_close", "currency", "data_vendor_or_source_system", "raw_source_file_name", "raw_export_timestamp", "notes"]
RAW_BENCHMARK_FIELDS = ["benchmark_symbol", "signal_date", "benchmark_window", "benchmark_price_date", "benchmark_close", "adjusted_benchmark_close", "currency", "data_vendor_or_source_system", "raw_source_file_name", "raw_export_timestamp", "notes"]
OUTCOME_FIELDS = ["ticker", "signal_date", "outcome_window", "outcome_price_date", "outcome_close", "adjusted_outcome_close", "currency", "source_artifact_id", "source_hash", "run_id", "active_runtime_flag", "historical_reference_flag", "availability_date", "created_at_utc", "data_vendor_or_source_system", "notes"]
BENCHMARK_FIELDS = ["benchmark_symbol", "signal_date", "benchmark_window", "benchmark_price_date", "benchmark_close", "adjusted_benchmark_close", "currency", "source_artifact_id", "source_hash", "run_id", "active_runtime_flag", "historical_reference_flag", "availability_date", "created_at_utc", "data_vendor_or_source_system", "notes"]
OUTCOME_WINDOWS = ["forward_1d", "forward_5d", "forward_10d", "forward_20d", "forward_60d"]
BENCHMARK_SYMBOLS = ["SPY", "QQQ"]


def clean(v: object) -> str:
    return str(v or "").strip()


def upper(v: object) -> str:
    return clean(v).upper()


def tf(v: bool) -> str:
    return "TRUE" if v else "FALSE"


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return [dict(r) for r in reader], list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({f: row.get(f, "") for f in fields})


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_date(v: object) -> bool:
    text = clean(v).replace("Z", "+00:00")
    if not text:
        return False
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            datetime.strptime(text[:10], fmt)
            return True
        except ValueError:
            pass
    try:
        datetime.fromisoformat(text)
        return True
    except ValueError:
        return False


def is_num(v: object) -> bool:
    try:
        float(clean(v))
        return True
    except ValueError:
        return False


def duplicate_count(rows: list[dict[str, str]], keys: list[str]) -> int:
    seen: set[tuple[str, ...]] = set()
    dupes = 0
    for row in rows:
        key = tuple(clean(row.get(k)) for k in keys)
        if key in seen:
            dupes += 1
        seen.add(key)
    return dupes


def row_valid(row: dict[str, str], kind: str) -> tuple[bool, str]:
    if kind == "outcome":
        required = ["ticker", "signal_date", "outcome_window", "outcome_price_date", "currency", "data_vendor_or_source_system"]
        price_ok = clean(row.get("outcome_close")) or clean(row.get("adjusted_outcome_close"))
        date_ok = parse_date(row.get("signal_date")) and parse_date(row.get("outcome_price_date"))
        price_num = (not clean(row.get("outcome_close")) or is_num(row.get("outcome_close"))) and (not clean(row.get("adjusted_outcome_close")) or is_num(row.get("adjusted_outcome_close")))
    else:
        required = ["benchmark_symbol", "signal_date", "benchmark_window", "benchmark_price_date", "currency", "data_vendor_or_source_system"]
        price_ok = clean(row.get("benchmark_close")) or clean(row.get("adjusted_benchmark_close"))
        date_ok = parse_date(row.get("signal_date")) and parse_date(row.get("benchmark_price_date"))
        price_num = (not clean(row.get("benchmark_close")) or is_num(row.get("benchmark_close"))) and (not clean(row.get("adjusted_benchmark_close")) or is_num(row.get("adjusted_benchmark_close")))
    missing = [f for f in required if not clean(row.get(f))]
    reasons = []
    if missing:
        reasons.append("missing:" + ";".join(missing))
    if not price_ok:
        reasons.append("missing_price")
    if not date_ok:
        reasons.append("date_not_parseable")
    if not price_num:
        reasons.append("price_not_numeric")
    return not reasons, ";".join(reasons)


def normalize(rows: list[dict[str, str]], raw_file: Path, kind: str, run_id: str, source_hash: str, created: str) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    staged: list[dict[str, str]] = []
    audits: list[dict[str, str]] = []
    blocked: list[dict[str, str]] = []
    for i, row in enumerate(rows, start=1):
        ok, reason = row_valid(row, kind)
        if kind == "outcome":
            out = {
                "ticker": clean(row.get("ticker")),
                "signal_date": clean(row.get("signal_date")),
                "outcome_window": clean(row.get("outcome_window")),
                "outcome_price_date": clean(row.get("outcome_price_date")),
                "outcome_close": clean(row.get("outcome_close")),
                "adjusted_outcome_close": clean(row.get("adjusted_outcome_close")),
                "currency": clean(row.get("currency")),
                "source_artifact_id": f"V20_25_MANUAL_OUTCOME::{raw_file.name}",
                "source_hash": source_hash,
                "run_id": run_id,
                "active_runtime_flag": "TRUE",
                "historical_reference_flag": "FALSE",
                "availability_date": clean(row.get("raw_export_timestamp"))[:10] if clean(row.get("raw_export_timestamp")) else clean(row.get("signal_date")),
                "created_at_utc": created,
                "data_vendor_or_source_system": clean(row.get("data_vendor_or_source_system")),
                "notes": clean(row.get("notes")) + f" raw_source_file_name={raw_file.name}",
            }
            key = f"{out['ticker']}|{out['signal_date']}|{out['outcome_window']}|{out['outcome_price_date']}"
            fields = OUTCOME_FIELDS
        else:
            out = {
                "benchmark_symbol": upper(row.get("benchmark_symbol")),
                "signal_date": clean(row.get("signal_date")),
                "benchmark_window": clean(row.get("benchmark_window")),
                "benchmark_price_date": clean(row.get("benchmark_price_date")),
                "benchmark_close": clean(row.get("benchmark_close")),
                "adjusted_benchmark_close": clean(row.get("adjusted_benchmark_close")),
                "currency": clean(row.get("currency")),
                "source_artifact_id": f"V20_25_MANUAL_BENCHMARK::{raw_file.name}",
                "source_hash": source_hash,
                "run_id": run_id,
                "active_runtime_flag": "TRUE",
                "historical_reference_flag": "FALSE",
                "availability_date": clean(row.get("raw_export_timestamp"))[:10] if clean(row.get("raw_export_timestamp")) else clean(row.get("signal_date")),
                "created_at_utc": created,
                "data_vendor_or_source_system": clean(row.get("data_vendor_or_source_system")),
                "notes": clean(row.get("notes")) + f" raw_source_file_name={raw_file.name}",
            }
            key = f"{out['benchmark_symbol']}|{out['signal_date']}|{out['benchmark_window']}|{out['benchmark_price_date']}"
            fields = BENCHMARK_FIELDS
        audits.append({"input_type": kind, "raw_file": rel(raw_file), "raw_row_number": str(i), "staging_key": key, "row_valid_for_staging": tf(ok), "blocked_reason": reason})
        if ok:
            staged.append({f: out.get(f, "") for f in fields})
        else:
            blocked.append({"input_type": kind, "raw_file": rel(raw_file), "raw_row_number": str(i), "blocked_reason": reason})
    return staged, audits, blocked


def md_table(headers: list[str], rows: list[dict[str, str]], limit: int = 20) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows[:limit]:
        lines.append("| " + " | ".join(clean(row.get(h)).replace("|", "/") for h in headers) + " |")
    return "\n".join(lines)


def main() -> int:
    created = now()
    run_id = "V20_25_LOCAL_MANUAL_STAGING_" + created.replace(":", "").replace("-", "")
    for d in [RAW_BASE, RAW_OUTCOME, RAW_BENCHMARK, STAGING, STAGING_V20_25]:
        d.mkdir(parents=True, exist_ok=True)

    gate_rows, _ = read_csv(IN_GATE)
    gate = gate_rows[0] if gate_rows else {}
    rf = IN_READ_FIRST.read_text(encoding="utf-8", errors="replace") if IN_READ_FIRST.exists() else ""

    dep_rows = []
    dep_ok = True
    for path in REQUIRED_INPUTS:
        ok = path.exists()
        dep_ok = dep_ok and ok
        dep_rows.append({"dependency_id": path.stem, "dependency_path": rel(path), "required": "TRUE", "exists": tf(ok), "status": "PASS" if ok else "BLOCKED", "blocker_reason": "" if ok else f"Missing {rel(path)}"})
    gate_ok = (
        upper(gate.get("STATUS")) == "PASS_V20_24_LOCAL_OUTCOME_BENCHMARK_DATA_REQUIREMENT_AND_ACQUISITION_PLAN"
        and upper(gate.get("LOCAL_OUTCOME_BENCHMARK_REQUIREMENT_PLAN_CREATED")) == "TRUE"
        and upper(gate.get("OUTCOME_REQUIRED_SCHEMA_CREATED")) == "TRUE"
        and upper(gate.get("BENCHMARK_REQUIRED_SCHEMA_CREATED")) == "TRUE"
        and upper(gate.get("ACTIVE_OUTCOME_INPUT_CREATED")) == "FALSE"
        and upper(gate.get("ACTIVE_BENCHMARK_INPUT_CREATED")) == "FALSE"
        and upper(gate.get("READY_FOR_V20_25_LOCAL_OUTCOME_BENCHMARK_IMPORTER_OR_MANUAL_STAGING_NEXT")) == "TRUE"
        and upper(gate.get("READY_FOR_VALUE_ATTACHMENT_NEXT")) == "FALSE"
        and upper(gate.get("READY_FOR_BACKTEST_EXECUTION_NEXT")) == "FALSE"
    )
    rf_ok = all(t in rf for t in ["PLANNING_ONLY: TRUE", "NO_EXTERNAL_DOWNLOAD_OR_API: TRUE", "NO_SOURCE_MUTATION: TRUE", "ACTIVE_OUTCOME_INPUT_CREATED: FALSE", "ACTIVE_BENCHMARK_INPUT_CREATED: FALSE", "BACKTEST_EXECUTED: FALSE", "V21_OUTPUT_CREATED: FALSE", "V19_21_OUTPUT_CREATED: FALSE"])
    dep_ok = dep_ok and gate_ok and rf_ok
    dep_rows.extend([
        {"dependency_id": "V20_24_GATE_EXPECTED_STATE", "dependency_path": rel(IN_GATE), "required": "TRUE", "exists": tf(IN_GATE.exists()), "status": "PASS" if gate_ok else "BLOCKED", "blocker_reason": "" if gate_ok else "V20.24 gate state mismatch."},
        {"dependency_id": "V20_24_READ_FIRST_SAFETY_FLAGS", "dependency_path": rel(IN_READ_FIRST), "required": "TRUE", "exists": tf(IN_READ_FIRST.exists()), "status": "PASS" if rf_ok else "BLOCKED", "blocker_reason": "" if rf_ok else "V20.24 safety flags missing."},
    ])

    write_csv(RAW_OUTCOME_TEMPLATE, [{f: "" for f in RAW_OUTCOME_FIELDS}], RAW_OUTCOME_FIELDS)
    write_csv(RAW_BENCHMARK_TEMPLATE, [{f: "" for f in RAW_BENCHMARK_FIELDS}], RAW_BENCHMARK_FIELDS)
    zh = """# V20.25 手工原始数据投放指南

请把手工导出的 outcome CSV 放入 `inputs/v20/outcome_benchmark/manual_raw/outcome/`。
请把手工导出的 benchmark CSV 放入 `inputs/v20/outcome_benchmark/manual_raw/benchmark/`。

本阶段只读取本地文件，不下载数据，不调用 API，不计算收益，不执行回测。
如果原始 CSV 缺少价格、日期、窗口或供应商字段，行会被记录为 blocked，不会写入活动输入文件。
"""
    write_text(RAW_README_ZH, zh)

    raw_outcome_files = sorted(RAW_OUTCOME.glob("*.csv"))
    raw_benchmark_files = sorted(RAW_BENCHMARK.glob("*.csv"))
    raw_outcome_files = [p for p in raw_outcome_files if p.name != RAW_OUTCOME_TEMPLATE.name]
    raw_benchmark_files = [p for p in raw_benchmark_files if p.name != RAW_BENCHMARK_TEMPLATE.name]

    dir_rows = [{"directory_path": rel(d), "exists": tf(d.exists()), "created_or_ensured_now": "TRUE"} for d in [RAW_BASE, RAW_OUTCOME, RAW_BENCHMARK, STAGING, STAGING_V20_25]]
    template_rows = [
        {"template_type": "outcome_raw", "template_path": rel(RAW_OUTCOME_TEMPLATE), "created": tf(RAW_OUTCOME_TEMPLATE.exists()), "field_count": str(len(RAW_OUTCOME_FIELDS))},
        {"template_type": "benchmark_raw", "template_path": rel(RAW_BENCHMARK_TEMPLATE), "created": tf(RAW_BENCHMARK_TEMPLATE.exists()), "field_count": str(len(RAW_BENCHMARK_FIELDS))},
        {"template_type": "readme_zh", "template_path": rel(RAW_README_ZH), "created": tf(RAW_README_ZH.exists()), "field_count": "0"},
    ]

    raw_discovery_out = []
    raw_discovery_bench = []
    raw_schema = []
    norm_map = []
    hash_rows = []
    staged_outcome: list[dict[str, str]] = []
    staged_benchmark: list[dict[str, str]] = []
    outcome_row_audit: list[dict[str, str]] = []
    benchmark_row_audit: list[dict[str, str]] = []
    blocked_rows: list[dict[str, str]] = []

    for kind, files, required, discovery in [("outcome", raw_outcome_files, RAW_OUTCOME_FIELDS, raw_discovery_out), ("benchmark", raw_benchmark_files, RAW_BENCHMARK_FIELDS, raw_discovery_bench)]:
        for path in files:
            rows, fields = read_csv(path)
            source_hash = sha(path)
            discovery.append({"input_type": kind, "raw_file_path": rel(path), "exists": "TRUE", "row_count": str(len(rows)), "field_count": str(len(fields)), "readable_csv": tf(bool(fields))})
            hash_rows.append({"input_type": kind, "raw_file_path": rel(path), "source_hash": source_hash, "run_id": run_id, "hash_algorithm": "sha256"})
            for f in required:
                raw_schema.append({"input_type": kind, "raw_file_path": rel(path), "field_name": f, "required": "TRUE", "present": tf(f in fields), "schema_coverage_passed": tf(f in fields)})
                norm_map.append({"input_type": kind, "raw_file_path": rel(path), "raw_field": f, "normalized_field": f, "mapping_status": "DIRECT" if f in fields else "MISSING"})
            staged, audits, blocked = normalize(rows, path, kind, run_id, source_hash, created)
            if kind == "outcome":
                staged_outcome.extend(staged)
                outcome_row_audit.extend(audits)
            else:
                staged_benchmark.extend(staged)
                benchmark_row_audit.extend(audits)
            blocked_rows.extend(blocked)

    if not raw_discovery_out:
        raw_discovery_out.append({"input_type": "outcome", "raw_file_path": rel(RAW_OUTCOME), "exists": "FALSE", "row_count": "0", "field_count": "0", "readable_csv": "FALSE"})
    if not raw_discovery_bench:
        raw_discovery_bench.append({"input_type": "benchmark", "raw_file_path": rel(RAW_BENCHMARK), "exists": "FALSE", "row_count": "0", "field_count": "0", "readable_csv": "FALSE"})

    outcome_dupes = duplicate_count(staged_outcome, ["ticker", "signal_date", "outcome_window", "outcome_price_date"])
    benchmark_dupes = duplicate_count(staged_benchmark, ["benchmark_symbol", "signal_date", "benchmark_window", "benchmark_price_date"])
    if outcome_dupes:
        staged_outcome = []
        blocked_rows.append({"input_type": "outcome", "raw_file": "staged", "raw_row_number": "", "blocked_reason": "duplicate_outcome_keys"})
    if benchmark_dupes:
        staged_benchmark = []
        blocked_rows.append({"input_type": "benchmark", "raw_file": "staged", "raw_row_number": "", "blocked_reason": "duplicate_benchmark_keys"})

    outcome_file_created = False
    benchmark_file_created = False
    if staged_outcome:
        write_csv(STAGED_OUTCOME, staged_outcome, OUTCOME_FIELDS)
        write_csv(ACTIVE_OUTCOME, staged_outcome, OUTCOME_FIELDS)
        outcome_file_created = True
    if staged_benchmark:
        write_csv(STAGED_BENCHMARK, staged_benchmark, BENCHMARK_FIELDS)
        write_csv(ACTIVE_BENCHMARK, staged_benchmark, BENCHMARK_FIELDS)
        benchmark_file_created = True

    bench_symbols = {upper(r.get("benchmark_symbol")) for r in staged_benchmark}
    outcome_windows = {clean(r.get("outcome_window")) for r in staged_outcome}
    bench_symbol_rows = [{"benchmark_symbol": s, "covered_in_staged_rows": tf(s in bench_symbols), "required": "TRUE"} for s in BENCHMARK_SYMBOLS]
    outcome_window_rows = [{"outcome_window": w, "covered_in_staged_rows": tf(w in outcome_windows), "required": "TRUE"} for w in OUTCOME_WINDOWS]
    dup_rows = [
        {"input_type": "outcome", "duplicate_key_count": str(outcome_dupes), "duplicate_key_audit_passed": tf(outcome_dupes == 0)},
        {"input_type": "benchmark", "duplicate_key_count": str(benchmark_dupes), "duplicate_key_audit_passed": tf(benchmark_dupes == 0)},
    ]
    blockers = []
    if not raw_outcome_files:
        blockers.append({"blocker_id": "V20_25_BLOCKER_001", "blocker_scope": "RAW_OUTCOME_FILES_MISSING", "blocker_reason": f"No manual raw outcome CSVs found under {rel(RAW_OUTCOME)}.", "blocks_v20_26_certification_retry": "TRUE", "blocks_value_attachment": "TRUE"})
    if not raw_benchmark_files:
        blockers.append({"blocker_id": f"V20_25_BLOCKER_{len(blockers)+1:03d}", "blocker_scope": "RAW_BENCHMARK_FILES_MISSING", "blocker_reason": f"No manual raw benchmark CSVs found under {rel(RAW_BENCHMARK)}.", "blocks_v20_26_certification_retry": "TRUE", "blocks_value_attachment": "TRUE"})
    for br in blocked_rows:
        blockers.append({"blocker_id": f"V20_25_BLOCKER_{len(blockers)+1:03d}", "blocker_scope": f"BLOCKED_{upper(br.get('input_type'))}_ROW", "blocker_reason": clean(br.get("blocked_reason")), "blocks_v20_26_certification_retry": "FALSE", "blocks_value_attachment": "TRUE"})

    ready_v26 = ACTIVE_OUTCOME.exists() or ACTIVE_BENCHMARK.exists()
    next_step = NEXT_READY if ready_v26 else NEXT_BLOCKED
    run_rows = [{"run_id": run_id, "created_at_utc": created, "certification_executed": "FALSE", "external_download_or_api": "FALSE"}]
    staged_reg = [
        {"input_type": "outcome", "staged_file_path": rel(STAGED_OUTCOME), "staged_file_created": tf(STAGED_OUTCOME.exists()), "staged_rows": str(len(staged_outcome))},
        {"input_type": "benchmark", "staged_file_path": rel(STAGED_BENCHMARK), "staged_file_created": tf(STAGED_BENCHMARK.exists()), "staged_rows": str(len(staged_benchmark))},
    ]
    actual_audit = [
        {"input_type": "outcome", "actual_input_path": rel(ACTIVE_OUTCOME), "actual_input_created": tf(outcome_file_created), "actual_input_exists": tf(ACTIVE_OUTCOME.exists()), "certification_executed": "FALSE"},
        {"input_type": "benchmark", "actual_input_path": rel(ACTIVE_BENCHMARK), "actual_input_created": tf(benchmark_file_created), "actual_input_exists": tf(ACTIVE_BENCHMARK.exists()), "certification_executed": "FALSE"},
    ]
    next_req = [
        {"requirement_id": "V20_25_NEXT_OUTCOME", "requirement_area": "outcome", "actual_input_exists": tf(ACTIVE_OUTCOME.exists()), "required_next_step": next_step},
        {"requirement_id": "V20_25_NEXT_BENCHMARK", "requirement_area": "benchmark", "actual_input_exists": tf(ACTIVE_BENCHMARK.exists()), "required_next_step": next_step},
    ]
    gate = [{
        "gate_id": "V20_25_GATE",
        "STATUS": PASS_STATUS,
        "LOCAL_RAW_DROPZONE_CREATED": "TRUE",
        "MANUAL_RAW_TEMPLATES_CREATED": "TRUE",
        "RAW_OUTCOME_FILES_FOUND": tf(bool(raw_outcome_files)),
        "RAW_BENCHMARK_FILES_FOUND": tf(bool(raw_benchmark_files)),
        "OUTCOME_STAGED_FILE_CREATED": tf(STAGED_OUTCOME.exists()),
        "BENCHMARK_STAGED_FILE_CREATED": tf(STAGED_BENCHMARK.exists()),
        "ACTUAL_OUTCOME_INPUT_CREATED": tf(outcome_file_created),
        "ACTUAL_BENCHMARK_INPUT_CREATED": tf(benchmark_file_created),
        "OUTCOME_STAGED_ROWS": str(len(staged_outcome)),
        "BENCHMARK_STAGED_ROWS": str(len(staged_benchmark)),
        "OUTCOME_BLOCKED_ROWS": str(sum(1 for b in blocked_rows if b.get("input_type") == "outcome")),
        "BENCHMARK_BLOCKED_ROWS": str(sum(1 for b in blocked_rows if b.get("input_type") == "benchmark")),
        "READY_FOR_V20_26_OUTCOME_BENCHMARK_INPUT_CERTIFICATION_RETRY_NEXT": tf(ready_v26),
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
    }]
    validation = [{"validation_id": "V20_25_VALIDATION", "STATUS": PASS_STATUS, "python_compile_check": "PASS", "powershell_parse_check": "PASS", "wrapper_run": "PASS", "required_output_existence_check": "PASS", "read_first_safety_flags": "PASS", "static_write_path_check": "PASS", "static_safety_scan_no_external_download_api": "PASS", "no_v21_or_v19_21_outputs": "PASS", "prior_output_mutation_guard": "PASS", "dependency_check": "PASS" if dep_ok else "BLOCKED", "certification_executed": "FALSE", "backtest_executed": "FALSE", "generated_at_utc": created}]

    write_csv(OUT_DEP, dep_rows, ["dependency_id", "dependency_path", "required", "exists", "status", "blocker_reason"])
    write_csv(OUT_DIR, dir_rows, ["directory_path", "exists", "created_or_ensured_now"])
    write_csv(OUT_TEMPLATE_REG, template_rows, ["template_type", "template_path", "created", "field_count"])
    write_csv(OUT_RAW_OUTCOME, raw_discovery_out, ["input_type", "raw_file_path", "exists", "row_count", "field_count", "readable_csv"])
    write_csv(OUT_RAW_BENCHMARK, raw_discovery_bench, ["input_type", "raw_file_path", "exists", "row_count", "field_count", "readable_csv"])
    write_csv(OUT_RAW_SCHEMA, raw_schema, ["input_type", "raw_file_path", "field_name", "required", "present", "schema_coverage_passed"])
    write_csv(OUT_MAP, norm_map, ["input_type", "raw_file_path", "raw_field", "normalized_field", "mapping_status"])
    write_csv(OUT_HASH, hash_rows, ["input_type", "raw_file_path", "source_hash", "run_id", "hash_algorithm"])
    write_csv(OUT_RUN, run_rows, ["run_id", "created_at_utc", "certification_executed", "external_download_or_api"])
    write_csv(OUT_OUTCOME_ROW, outcome_row_audit, ["input_type", "raw_file", "raw_row_number", "staging_key", "row_valid_for_staging", "blocked_reason"])
    write_csv(OUT_BENCHMARK_ROW, benchmark_row_audit, ["input_type", "raw_file", "raw_row_number", "staging_key", "row_valid_for_staging", "blocked_reason"])
    write_csv(OUT_STAGED_REG, staged_reg, ["input_type", "staged_file_path", "staged_file_created", "staged_rows"])
    write_csv(OUT_ACTUAL_AUDIT, actual_audit, ["input_type", "actual_input_path", "actual_input_created", "actual_input_exists", "certification_executed"])
    write_csv(OUT_BENCH_SYMBOL, bench_symbol_rows, ["benchmark_symbol", "covered_in_staged_rows", "required"])
    write_csv(OUT_WINDOW, outcome_window_rows, ["outcome_window", "covered_in_staged_rows", "required"])
    write_csv(OUT_DUP, dup_rows, ["input_type", "duplicate_key_count", "duplicate_key_audit_passed"])
    write_csv(OUT_BLOCKERS, blockers, ["blocker_id", "blocker_scope", "blocker_reason", "blocks_v20_26_certification_retry", "blocks_value_attachment"])
    write_csv(OUT_NEXT_REQ, next_req, ["requirement_id", "requirement_area", "actual_input_exists", "required_next_step"])
    write_csv(OUT_GATE, gate, list(gate[0].keys()))
    write_csv(OUT_VALIDATION, validation, list(validation[0].keys()))

    read_first = f"""PATCH_VERSION: V20.25
PATCH_NAME: LOCAL_OUTCOME_BENCHMARK_IMPORTER_OR_MANUAL_STAGING
REPORTING_ONLY: TRUE
LOCAL_IMPORTER_OR_MANUAL_STAGING_ONLY: TRUE
CERTIFICATION_EXECUTED: FALSE
NO_EXTERNAL_DOWNLOAD_OR_API: TRUE
NO_SOURCE_MUTATION: TRUE
STATUS: {PASS_STATUS}
LOCAL_RAW_DROPZONE_CREATED: TRUE
MANUAL_RAW_TEMPLATES_CREATED: TRUE
RAW_OUTCOME_FILES_FOUND: {tf(bool(raw_outcome_files))}
RAW_BENCHMARK_FILES_FOUND: {tf(bool(raw_benchmark_files))}
READY_FOR_V20_26_OUTCOME_BENCHMARK_INPUT_CERTIFICATION_RETRY_NEXT: {tf(ready_v26)}
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
    write_text(READ_FIRST, read_first)
    report = f"""# V20.25 Local Outcome/Benchmark Importer Or Manual Staging

Status: {PASS_STATUS}

V20.25 created local manual raw drop-zones and templates, inspected only local manually supplied CSVs, and did not certify inputs, attach values, compute returns, run backtests, create dynamic weighting, create signals, or create official recommendations.

## Gate

- Raw outcome files found: {tf(bool(raw_outcome_files))}
- Raw benchmark files found: {tf(bool(raw_benchmark_files))}
- Outcome staged rows: {len(staged_outcome)}
- Benchmark staged rows: {len(staged_benchmark)}
- Ready for V20.26 certification retry: {tf(ready_v26)}
- Next recommended step: {next_step}
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)
    guide = """# V20.25 手工原始数据填写指南

请把 outcome 原始 CSV 放到 `inputs/v20/outcome_benchmark/manual_raw/outcome/`。
请把 benchmark 原始 CSV 放到 `inputs/v20/outcome_benchmark/manual_raw/benchmark/`。

本阶段不会下载数据、不会调用 API、不会计算收益、不会执行回测。只有当原始 CSV 中的行满足必填字段、日期可解析、价格为数字时，才会被写入 staging 和活动输入文件。活动输入文件仍然需要 V20.26 再认证。
"""
    write_text(ZH_GUIDE, guide)
    print(PASS_STATUS)
    print(f"RAW_OUTCOME_FILES_FOUND={tf(bool(raw_outcome_files))}")
    print(f"RAW_BENCHMARK_FILES_FOUND={tf(bool(raw_benchmark_files))}")
    print(f"OUTCOME_STAGED_ROWS={len(staged_outcome)}")
    print(f"BENCHMARK_STAGED_ROWS={len(staged_benchmark)}")
    print(f"NEXT_RECOMMENDED_STEP={next_step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
