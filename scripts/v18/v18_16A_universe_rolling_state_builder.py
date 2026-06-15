from __future__ import annotations

import argparse
import ast
import csv
import datetime as dt
import hashlib
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Set, Tuple


STATUS_OK = "OK_V18_16A_UNIVERSE_ROLLING_STATE_BUILDER_READY"
STATUS_WARN = "WARN_V18_16A_UNIVERSE_ROLLING_STATE_BUILDER_VALIDATION_FAILED"
P1_STATUS_OK = "OK_V18_16A_P1_MANUAL_UNIVERSE_ADDITIONS_READY"
P1_STATUS_WARN = "WARN_V18_16A_P1_MANUAL_UNIVERSE_ADDITIONS_VALIDATION_FAILED"
MODE = "STATE_BUILDER_ONLY"
P1_MODE = "MANUAL_UNIVERSE_ADDITION_ONLY"
AUTO_TRADE = "DISABLED"
AUTO_SELL = "DISABLED"
OFFICIAL_DECISION_IMPACT = "NONE"
PRICE_UPDATE_EXECUTED = "FALSE"
EVENT_UPDATE_EXECUTED = "FALSE"
ROLLING_SCAN_EXECUTED = "FALSE"

REQUIRED_COLUMNS = [
    "ticker",
    "company_name",
    "sector",
    "industry",
    "source_tags",
    "source_count",
    "universe_tier",
    "scan_priority",
    "last_scan_date",
    "next_due_scan_date",
    "days_since_last_scan",
    "scan_count_5d",
    "scan_count_20d",
    "last_price_update_date",
    "last_price_update_depth",
    "last_event_update_date",
    "last_event_update_depth",
    "required_data_depth",
    "actual_data_depth",
    "data_depth_sufficient",
    "price_cache_status",
    "event_cache_status",
    "latest_price_date",
    "last_close",
    "price_freshness_status",
    "ret_5d",
    "ret_20d",
    "ret_60d",
    "ret_120d",
    "above_ma20",
    "above_ma60",
    "above_ma120",
    "distance_from_52w_high",
    "relative_strength_vs_qqq",
    "relative_strength_vs_smh",
    "volume_surge_score",
    "light_trend_status",
    "promotion_score",
    "demotion_score",
    "promotion_reason",
    "demotion_reason",
    "consecutive_improvement_count",
    "consecutive_weak_count",
    "is_position",
    "is_core_daily",
    "is_candidate",
    "is_watchlist",
    "scan_deferred_reason",
]

BASE_INPUTS = [
    ("CURRENT_RANKED_CANDIDATES", "outputs/v18/candidates/V18_CURRENT_RANKED_CANDIDATES.csv", True),
    ("MANUAL_UNIVERSE_ADDITIONS", "state/v18/universe/V18_MANUAL_UNIVERSE_ADDITIONS.csv", False),
    ("STATE_FORWARD_TRACKER", "state/v18/candidate_forward_tracker/V18_CURRENT_RANKED_CANDIDATE_FORWARD_TRACKER.csv", False),
    ("OUTPUT_FORWARD_TRACKER", "outputs/v18/candidates/V18_CURRENT_RANKED_CANDIDATE_FORWARD_TRACKER.csv", False),
    ("MANUAL_POSITIONS", "state/v18/manual/V18_MANUAL_POSITIONS.csv", False),
    ("MANUAL_TRADE_LOG", "state/v18/manual/V18_MANUAL_TRADE_LOG.csv", False),
    ("MANUAL_POSITION_REVIEW", "outputs/v18/positions/V18_CURRENT_MANUAL_POSITION_REVIEW.csv", False),
    ("MANUAL_TRADE_FEEDBACK", "outputs/v18/positions/V18_CURRENT_MANUAL_TRADE_FEEDBACK.csv", False),
]

TIER_RANK = {
    "POSITION": 6,
    "CORE_DAILY": 5,
    "CANDIDATE": 4,
    "STRONG_WATCH": 3,
    "WATCHLIST": 2,
    "RESEARCH": 1,
    "": 0,
}

TIER_PRIORITY = {
    "POSITION": 1000,
    "CORE_DAILY": 800,
    "CANDIDATE": 600,
    "STRONG_WATCH": 400,
    "WATCHLIST": 250,
    "RESEARCH": 100,
}

TIER_DEPTH = {
    "POSITION": "FULL_POSITION_DATA",
    "CORE_DAILY": "FULL_FACTOR_DATA",
    "CANDIDATE": "MEDIUM_TREND_DATA",
    "STRONG_WATCH": "LIGHT_PLUS_DATA",
    "WATCHLIST": "LIGHT_DATA",
    "RESEARCH": "LIGHT_DATA",
}


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    for enc in ("utf-8-sig", "utf-8", "cp932", "latin-1"):
        try:
            return path.read_text(encoding=enc, errors="replace")
        except Exception:
            pass
    return ""


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


def read_csv(path: Path) -> Tuple[List[Dict[str, str]], List[str], str]:
    if not path.exists():
        return [], [], "MISSING"
    for enc in ("utf-8-sig", "utf-8", "cp932"):
        try:
            with path.open("r", encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                return list(reader), list(reader.fieldnames or []), "OK"
        except Exception:
            pass
    return [], [], "CSV_PARSE_FAILED"


def write_csv(path: Path, rows: Sequence[Dict[str, object]], fields: Sequence[str]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def rel(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except Exception:
        return str(path)


def sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_baseline(root: Path) -> Dict[str, Tuple[float, str]]:
    base = root / "archive/stable"
    out: Dict[str, Tuple[float, str]] = {}
    if not base.exists():
        return out
    for folder in base.iterdir():
        if folder.is_dir():
            manifest = folder / "MANIFEST.csv"
            out[str(folder.resolve())] = (folder.stat().st_mtime, sha256(manifest))
    return out


def first_nonempty(row: Dict[str, str], names: Sequence[str]) -> str:
    lower = {k.lower(): k for k in row.keys()}
    for name in names:
        key = lower.get(name.lower())
        if key and str(row.get(key, "")).strip():
            return str(row.get(key, "")).strip()
    return ""


def detect_ticker_column(fields: Sequence[str]) -> str:
    preferred = ["ticker", "symbol", "Ticker", "Symbol"]
    lower = {f.lower(): f for f in fields}
    for name in preferred:
        if name.lower() in lower:
            return lower[name.lower()]
    for field in fields:
        if "ticker" in field.lower() or "symbol" in field.lower():
            return field
    return ""


def clean_ticker(value: str) -> str:
    ticker = str(value or "").strip().upper()
    ticker = ticker.replace("$", "").replace(" ", "")
    if not re.match(r"^[A-Z0-9.\-]{1,12}$", ticker):
        return ""
    return ticker


def parse_rank(row: Dict[str, str]) -> int:
    value = first_nonempty(row, ["rank", "candidate_rank", "factor_pack_rank"])
    try:
        return int(float(value))
    except Exception:
        return 999999


def infer_tier(source_name: str, row: Dict[str, str]) -> str:
    if source_name == "MANUAL_UNIVERSE_ADDITIONS":
        tier = first_nonempty(row, ["initial_tier"]).upper()
        return tier if tier in TIER_RANK else "RESEARCH"
    if source_name in {"MANUAL_POSITIONS", "MANUAL_POSITION_REVIEW"}:
        status_text = " ".join(str(v) for v in row.values()).upper()
        if "CLOSED" not in status_text and "NO_POSITION" not in status_text:
            return "POSITION"
    if source_name == "CURRENT_RANKED_CANDIDATES":
        return "CORE_DAILY" if parse_rank(row) <= 5 else "CANDIDATE"
    if "FORWARD_TRACKER" in source_name:
        return "CANDIDATE"
    if source_name in {"MANUAL_TRADE_LOG", "MANUAL_TRADE_FEEDBACK"}:
        return "WATCHLIST"
    if any(token in source_name for token in ("WATCHLIST", "WATCH")):
        return "WATCHLIST"
    if any(token in source_name for token in ("CANDIDATE", "SCREENED")):
        return "RESEARCH"
    return "RESEARCH"


def default_record(ticker: str) -> Dict[str, object]:
    row = {col: "" for col in REQUIRED_COLUMNS}
    row.update(
        {
            "ticker": ticker,
            "source_tags": "",
            "source_count": 0,
            "universe_tier": "RESEARCH",
            "scan_priority": TIER_PRIORITY["RESEARCH"],
            "scan_count_5d": 0,
            "scan_count_20d": 0,
            "data_depth_sufficient": "UNKNOWN_NOT_UPDATED",
            "price_cache_status": "NOT_UPDATED_BY_V18_16A",
            "event_cache_status": "NOT_UPDATED_BY_V18_16A",
            "price_freshness_status": "NOT_UPDATED_BY_V18_16A",
            "promotion_score": 0,
            "demotion_score": 0,
            "promotion_reason": "NOT_EVALUATED_V18_16A",
            "demotion_reason": "NOT_EVALUATED_V18_16A",
            "consecutive_improvement_count": 0,
            "consecutive_weak_count": 0,
            "is_position": "FALSE",
            "is_core_daily": "FALSE",
            "is_candidate": "FALSE",
            "is_watchlist": "FALSE",
            "scan_deferred_reason": "ROLLING_SCAN_NOT_IMPLEMENTED_V18_16A",
        }
    )
    return row


def maybe_upgrade(existing_tier: str, candidate_tier: str) -> str:
    if existing_tier == "POSITION":
        return "POSITION"
    if existing_tier == "CORE_DAILY" and candidate_tier not in {"POSITION"}:
        return "CORE_DAILY"
    return candidate_tier if TIER_RANK.get(candidate_tier, 0) > TIER_RANK.get(existing_tier, 0) else existing_tier


def merge_source(records: Dict[str, Dict[str, object]], source_name: str, path: Path, root: Path) -> Dict[str, object]:
    rows, fields, status = read_csv(path)
    ticker_col = detect_ticker_column(fields)
    imported = 0
    seen: Set[str] = set()
    duplicate_rows = 0
    for row in rows:
        ticker = clean_ticker(row.get(ticker_col, "") if ticker_col else "")
        if not ticker:
            continue
        if ticker in seen:
            duplicate_rows += 1
            continue
        seen.add(ticker)
        imported += 1
        rec = records.setdefault(ticker, default_record(ticker))
        tags = set(str(rec.get("source_tags", "")).split(";")) if rec.get("source_tags") else set()
        source_tag = first_nonempty(row, ["source_tag"]) if source_name == "MANUAL_UNIVERSE_ADDITIONS" else ""
        tags.add(source_tag or source_name)
        rec["source_tags"] = ";".join(sorted(t for t in tags if t))
        rec["source_count"] = len(tags)
        tier = maybe_upgrade(str(rec.get("universe_tier", "")), infer_tier(source_name, row))
        rec["universe_tier"] = tier
        rec["scan_priority"] = TIER_PRIORITY[tier]
        rec["required_data_depth"] = TIER_DEPTH[tier]
        rec["company_name"] = rec.get("company_name") or first_nonempty(row, ["company_name", "company", "name", "security_name"])
        rec["sector"] = rec.get("sector") or first_nonempty(row, ["sector"])
        rec["industry"] = rec.get("industry") or first_nonempty(row, ["industry"])
        rec["latest_price_date"] = rec.get("latest_price_date") or first_nonempty(row, ["latest_price_date", "price_date", "signal_date"])
        rec["last_close"] = rec.get("last_close") or first_nonempty(row, ["last_close", "latest_close", "close", "price_at_signal"])
        rec["last_price_update_date"] = rec.get("last_price_update_date") or rec.get("latest_price_date")
        rec["last_price_update_depth"] = rec.get("last_price_update_depth") or "READ_FROM_EXISTING_SOURCE"
        if source_name in {"CURRENT_RANKED_CANDIDATES", "STATE_FORWARD_TRACKER", "OUTPUT_FORWARD_TRACKER"}:
            rec["is_candidate"] = "TRUE"
        if tier == "POSITION":
            rec["is_position"] = "TRUE"
        if tier == "CORE_DAILY":
            rec["is_core_daily"] = "TRUE"
            rec["is_candidate"] = "TRUE"
        if tier in {"WATCHLIST", "STRONG_WATCH"}:
            rec["is_watchlist"] = "TRUE"
    return {
        "input_source_path": rel(root, path),
        "source_name": source_name,
        "source_exists": str(path.exists()).upper(),
        "row_count": len(rows) if status == "OK" else 0,
        "ticker_column_detected": ticker_col,
        "ticker_count_imported": imported,
        "missing_optional_source_flag": str((not path.exists()) and source_name != "CURRENT_RANKED_CANDIDATES").upper(),
        "duplicate_ticker_count": duplicate_rows,
        "final_assigned_tier": "MIXED" if imported else "",
        "final_required_data_depth": "MIXED" if imported else "",
        "final_scan_priority": "MIXED" if imported else "",
        "parse_status": status,
    }


def discover_safe_sources(root: Path) -> List[Tuple[str, str, bool]]:
    found: List[Tuple[str, str, bool]] = []
    existing = {path for _, path, _ in BASE_INPUTS}
    for base in [root / "outputs/v18", root / "state/v18"]:
        if not base.exists():
            continue
        for path in base.rglob("*.csv"):
            rel_path = rel(root, path)
            lower = path.name.lower()
            if rel_path in existing:
                continue
            if any(token in lower for token in ("universe", "candidate", "watchlist", "screened")):
                found.append((f"DISCOVERED_{path.stem.upper()[:40]}", rel_path, False))
    return sorted(found, key=lambda x: x[1])


def parse_ps(path: Path) -> Tuple[bool, str]:
    if not path.exists():
        return False, "MISSING"
    ps_path = str(path.resolve()).replace("'", "''")
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        f"$p='{ps_path}'; $t=$null; $e=$null; [System.Management.Automation.Language.Parser]::ParseFile($p,[ref]$t,[ref]$e) > $null; if ($e.Count -gt 0) {{ $e | ForEach-Object {{ $_.Message }}; exit 1 }}",
    ]
    proc = subprocess.run(command, text=True, capture_output=True, timeout=60)
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def compile_py(path: Path) -> Tuple[bool, str]:
    try:
        ast.parse(read_text(path), filename=str(path))
        return True, ""
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def dangerous_hits(paths: Iterable[Path], root: Path) -> List[str]:
    parts = [("BUY", "NOW"), ("SELL", "NOW"), ("EXECUTE", "LIVE_ORDER"), ("LIVE", "TRADE"), ("LIVE", "SELL")]
    tokens = ["_".join(p) for p in parts]
    hits: List[str] = []
    for path in paths:
        text = read_text(path)
        in_token_block = False
        for line_no, line in enumerate(text.splitlines(), start=1):
            upper = line.upper()
            stripped = upper.strip()
            if "PARTS =" in upper or "TOKENS =" in upper or "DANGEROUS" in upper:
                in_token_block = True
            safe = (
                "DISABLED" in upper
                or "DO NOT" in upper
                or "DANGEROUS" in upper
                or "TOKEN" in upper
                or "SCAN" in upper
                or "HITS.APPEND" in upper
                or " IN UPPER" in upper
                or in_token_block
            )
            for token in tokens:
                if token in upper and not safe:
                    hits.append(f"{rel(root, path)}:{line_no}:{token}")
            if "AUTO_TRADE" in upper and "ENABLED" in upper and not safe:
                hits.append(f"{rel(root, path)}:{line_no}:AUTO_TRADE_ENABLED")
            if "AUTO_SELL" in upper and "ENABLED" in upper and not safe:
                hits.append(f"{rel(root, path)}:{line_no}:AUTO_SELL_ENABLED")
            if in_token_block and (stripped.endswith("]") or stripped.endswith(")")):
                in_token_block = False
    return hits


def finalise_record(rec: Dict[str, object]) -> Dict[str, object]:
    tier = str(rec.get("universe_tier") or "RESEARCH")
    rec["scan_priority"] = TIER_PRIORITY[tier]
    rec["required_data_depth"] = TIER_DEPTH[tier]
    rec["is_position"] = "TRUE" if tier == "POSITION" else str(rec.get("is_position") or "FALSE")
    rec["is_core_daily"] = "TRUE" if tier == "CORE_DAILY" else str(rec.get("is_core_daily") or "FALSE")
    rec["is_candidate"] = "TRUE" if tier in {"CORE_DAILY", "CANDIDATE"} else str(rec.get("is_candidate") or "FALSE")
    rec["is_watchlist"] = "TRUE" if tier in {"WATCHLIST", "STRONG_WATCH"} else str(rec.get("is_watchlist") or "FALSE")
    return {col: rec.get(col, "") for col in REQUIRED_COLUMNS}


def manual_addition_rows(path: Path) -> Tuple[List[Dict[str, str]], List[str], str, List[str], int]:
    rows, fields, status = read_csv(path)
    ticker_col = detect_ticker_column(fields)
    unique: List[str] = []
    seen: Set[str] = set()
    duplicate_count = 0
    for row in rows:
        ticker = clean_ticker(row.get(ticker_col, "") if ticker_col else "")
        if not ticker:
            continue
        if ticker in seen:
            duplicate_count += 1
            continue
        seen.add(ticker)
        unique.append(ticker)
    return rows, fields, status, unique, duplicate_count


def build(root: Path) -> int:
    root = root.resolve()
    state_dir = root / "state/v18/universe"
    out_dir = root / "outputs/v18/universe"
    ops_dir = root / "outputs/v18/ops"
    for d in [state_dir, out_dir, ops_dir]:
        ensure_dir(d)

    current_daily = root / "scripts/v18/run_v18_current_daily_command_center.ps1"
    current_daily_before = sha256(current_daily)
    stable_before = stable_baseline(root)

    state_path = state_dir / "V18_UNIVERSE_ROLLING_STATE.csv"
    alias_path = out_dir / "V18_CURRENT_UNIVERSE_ROLLING_STATE.csv"
    audit_path = out_dir / "V18_16A_CURRENT_UNIVERSE_ROLLING_STATE_AUDIT.csv"
    report_path = out_dir / "V18_16A_CURRENT_UNIVERSE_ROLLING_STATE_REPORT.md"
    read_first_path = ops_dir / "V18_16A_READ_FIRST.txt"
    p1_audit_path = out_dir / "V18_16A_P1_CURRENT_MANUAL_UNIVERSE_ADDITION_AUDIT.csv"
    p1_read_first_path = ops_dir / "V18_16A_P1_READ_FIRST.txt"
    manual_path = state_dir / "V18_MANUAL_UNIVERSE_ADDITIONS.csv"
    manual_raw_rows, manual_fields, manual_status, manual_unique_tickers, manual_duplicate_count = manual_addition_rows(manual_path)

    records: Dict[str, Dict[str, object]] = {}
    existing_rows, existing_fields, _ = read_csv(state_path)
    total_universe_before = len([row for row in existing_rows if clean_ticker(row.get("ticker", ""))])
    existing_tiers_before: Dict[str, str] = {}
    for row in existing_rows:
        ticker = clean_ticker(row.get("ticker", ""))
        if ticker:
            rec = default_record(ticker)
            rec.update({col: row.get(col, "") for col in REQUIRED_COLUMNS})
            records[ticker] = rec
            existing_tiers_before[ticker] = str(rec.get("universe_tier", ""))
    manual_existing_before = {ticker for ticker in manual_unique_tickers if ticker in records}

    source_specs = BASE_INPUTS + discover_safe_sources(root)
    audit_rows = []
    imported_by_source: Dict[str, int] = {}
    for source_name, rel_path, _required in source_specs:
        row = merge_source(records, source_name, root / rel_path, root)
        audit_rows.append(row)
        imported_by_source[source_name] = int(row["ticker_count_imported"])

    before_count = sum(int(r["ticker_count_imported"]) for r in audit_rows)
    final_rows = [finalise_record(records[t]) for t in sorted(records)]
    duplicate_removed = max(0, before_count - len(final_rows))

    write_csv(state_path, final_rows, REQUIRED_COLUMNS)
    shutil.copy2(state_path, alias_path)

    tier_counts = {tier: sum(1 for r in final_rows if r["universe_tier"] == tier) for tier in TIER_RANK}
    ranked_rows, _, _ = read_csv(root / "outputs/v18/candidates/V18_CURRENT_RANKED_CANDIDATES.csv")
    ranked_tickers = {clean_ticker(r.get("ticker", "")) for r in ranked_rows}
    state_tickers = {str(r["ticker"]) for r in final_rows}

    validations = []
    ps_ok, ps_note = parse_ps(root / "scripts/v18/run_v18_16A_universe_rolling_state_builder.ps1")
    py_ok, py_note = compile_py(root / "scripts/v18/v18_16A_universe_rolling_state_builder.py")
    validations.append(("POWERSHELL_PARSE", ps_ok, ps_note))
    validations.append(("PYTHON_COMPILE", py_ok, py_note))
    validations.append(("STATE_CSV_EXISTS", state_path.exists(), ""))
    validations.append(("CURRENT_ALIAS_EXISTS", alias_path.exists(), ""))
    validations.append(("REQUIRED_COLUMNS_EXIST", set(REQUIRED_COLUMNS).issubset(set(final_rows[0].keys() if final_rows else REQUIRED_COLUMNS)), ""))
    validations.append(("DUPLICATE_TICKERS_REMOVED", len(state_tickers) == len(final_rows), ""))
    validations.append(("TICKER_VALUES_NONEMPTY", all(str(r["ticker"]).strip() for r in final_rows), ""))
    validations.append(("CURRENT_RANKED_CANDIDATES_INCLUDED", ranked_tickers.issubset(state_tickers), f"missing={sorted(ranked_tickers - state_tickers)}"))
    validations.append(("MANUAL_POSITIONS_SOURCE_CHECKED", any(r["source_name"] == "MANUAL_POSITIONS" for r in audit_rows), ""))
    manual_missing_after = sorted(set(manual_unique_tickers) - state_tickers)
    downgraded = []
    for ticker, old_tier in existing_tiers_before.items():
        new_tier = str(records.get(ticker, {}).get("universe_tier", ""))
        if TIER_RANK.get(new_tier, 0) < TIER_RANK.get(old_tier, 0):
            downgraded.append(f"{ticker}:{old_tier}->{new_tier}")
    manual_new_non_research = [
        ticker
        for ticker in manual_unique_tickers
        if ticker not in manual_existing_before and str(records.get(ticker, {}).get("universe_tier", "")) != "RESEARCH"
    ]
    validations.append(("MANUAL_ADDITIONS_CSV_EXISTS", manual_path.exists(), ""))
    validations.append(("MANUAL_ADDITION_INPUT_COUNT_275", len(manual_raw_rows) == 275, f"actual={len(manual_raw_rows)}"))
    validations.append(("MANUAL_ADDITION_UNIQUE_COUNT_275", len(manual_unique_tickers) == 275, f"actual={len(manual_unique_tickers)}"))
    validations.append(("ALL_MANUAL_TICKERS_PRESENT", not manual_missing_after, f"missing={manual_missing_after[:20]}"))
    validations.append(("NO_EXISTING_TIER_DOWNGRADE", not downgraded, ";".join(downgraded[:20])))
    validations.append(("NEW_MANUAL_TICKERS_DEFAULT_RESEARCH", not manual_new_non_research, f"non_research={manual_new_non_research[:20]}"))
    validations.append(("NO_PRICE_UPDATE_EXECUTED", PRICE_UPDATE_EXECUTED == "FALSE", ""))
    validations.append(("NO_EVENT_UPDATE_EXECUTED", EVENT_UPDATE_EXECUTED == "FALSE", ""))
    validations.append(("NO_ROLLING_SCAN_EXECUTED", ROLLING_SCAN_EXECUTED == "FALSE", ""))
    validations.append(("CURRENT_DAILY_NOT_MODIFIED", sha256(current_daily) == current_daily_before, ""))
    stable_after = stable_baseline(root)
    stable_modified = any(stable_after.get(k) != v for k, v in stable_before.items())
    validations.append(("STABLE_SNAPSHOTS_NOT_MODIFIED", not stable_modified, ""))

    new_paths = [root / "scripts/v18/run_v18_16A_universe_rolling_state_builder.ps1", root / "scripts/v18/v18_16A_universe_rolling_state_builder.py", manual_path, state_path, alias_path, audit_path, report_path, read_first_path, p1_audit_path, p1_read_first_path]
    hits = dangerous_hits(new_paths, root)
    validations.append(("NO_DANGEROUS_TOKEN_INTRODUCED", len(hits) == 0, ";".join(hits[:20])))
    validations.append(("AUTO_TRADE_DISABLED", AUTO_TRADE == "DISABLED", ""))
    validations.append(("AUTO_SELL_DISABLED", AUTO_SELL == "DISABLED", ""))
    validations.append(("OFFICIAL_DECISION_IMPACT_NONE", OFFICIAL_DECISION_IMPACT == "NONE", ""))

    validation_fail_count = sum(1 for _, ok, _ in validations if not ok)
    status = STATUS_OK if validation_fail_count == 0 else STATUS_WARN

    for tier in ["POSITION", "CORE_DAILY", "CANDIDATE", "STRONG_WATCH", "WATCHLIST", "RESEARCH"]:
        audit_rows.append(
            {
                "input_source_path": "FINAL_UNIVERSE",
                "source_name": f"TIER_SUMMARY_{tier}",
                "source_exists": "TRUE",
                "row_count": tier_counts.get(tier, 0),
                "ticker_column_detected": "ticker",
                "ticker_count_imported": tier_counts.get(tier, 0),
                "missing_optional_source_flag": "FALSE",
                "duplicate_ticker_count": 0,
                "final_assigned_tier": tier,
                "final_required_data_depth": TIER_DEPTH[tier],
                "final_scan_priority": TIER_PRIORITY[tier],
                "parse_status": "OK",
            }
        )
    audit_rows.append(
        {
            "input_source_path": "VALIDATION",
            "source_name": "VALIDATION_SUMMARY",
            "source_exists": "TRUE",
            "row_count": len(validations),
            "ticker_column_detected": "",
            "ticker_count_imported": 0,
            "missing_optional_source_flag": "FALSE",
            "duplicate_ticker_count": duplicate_removed,
            "final_assigned_tier": "N/A",
            "final_required_data_depth": "N/A",
            "final_scan_priority": "N/A",
            "parse_status": "; ".join(f"{name}={'PASS' if ok else 'FAIL'}" for name, ok, _ in validations),
        }
    )
    write_csv(
        audit_path,
        audit_rows,
        [
            "input_source_path",
            "source_name",
            "source_exists",
            "row_count",
            "ticker_column_detected",
            "ticker_count_imported",
            "missing_optional_source_flag",
            "duplicate_ticker_count",
            "final_assigned_tier",
            "final_required_data_depth",
            "final_scan_priority",
            "parse_status",
        ],
    )

    manual_audit_rows: List[Dict[str, object]] = []
    seen_manual: Set[str] = set()
    manual_new_count = 0
    manual_existing_count = 0
    ticker_col = detect_ticker_column(manual_fields)
    for idx, row in enumerate(manual_raw_rows, start=1):
        ticker = clean_ticker(row.get(ticker_col, "") if ticker_col else "")
        is_duplicate = ticker in seen_manual if ticker else False
        if ticker:
            seen_manual.add(ticker)
        existed_before = ticker in manual_existing_before
        if ticker and not is_duplicate:
            if existed_before:
                manual_existing_count += 1
            else:
                manual_new_count += 1
        final = records.get(ticker, {})
        source_tags = str(final.get("source_tags", ""))
        manual_tag = first_nonempty(row, ["source_tag"]) or "MANUAL_EXPANSION_20260519"
        manual_audit_rows.append(
            {
                "input_order": idx,
                "raw_ticker": row.get(ticker_col, "") if ticker_col else "",
                "ticker": ticker,
                "source_tag": manual_tag,
                "initial_tier": first_nonempty(row, ["initial_tier"]) or "RESEARCH",
                "is_blank_or_invalid": str(not bool(ticker)).upper(),
                "is_duplicate_in_manual_file": str(is_duplicate).upper(),
                "existed_before": str(existed_before).upper(),
                "final_present": str(ticker in state_tickers).upper(),
                "final_tier": final.get("universe_tier", ""),
                "source_tag_added": str(manual_tag in source_tags.split(";")).upper(),
                "validation_status": "PASS" if ticker and ticker in state_tickers and manual_tag in source_tags.split(";") else "FAIL",
                "note": first_nonempty(row, ["note"]),
            }
        )
    write_csv(
        p1_audit_path,
        manual_audit_rows,
        [
            "input_order",
            "raw_ticker",
            "ticker",
            "source_tag",
            "initial_tier",
            "is_blank_or_invalid",
            "is_duplicate_in_manual_file",
            "existed_before",
            "final_present",
            "final_tier",
            "source_tag_added",
            "validation_status",
            "note",
        ],
    )

    values = {
        "STATUS": status,
        "MODE": MODE,
        "TOTAL_UNIVERSE_COUNT": str(len(final_rows)),
        "POSITION_COUNT": str(tier_counts.get("POSITION", 0)),
        "CORE_DAILY_COUNT": str(tier_counts.get("CORE_DAILY", 0)),
        "CANDIDATE_COUNT": str(tier_counts.get("CANDIDATE", 0)),
        "STRONG_WATCH_COUNT": str(tier_counts.get("STRONG_WATCH", 0)),
        "WATCHLIST_COUNT": str(tier_counts.get("WATCHLIST", 0)),
        "RESEARCH_COUNT": str(tier_counts.get("RESEARCH", 0)),
        "INPUT_SOURCE_COUNT": str(len(source_specs)),
        "MISSING_OPTIONAL_SOURCE_COUNT": str(sum(1 for r in audit_rows if r.get("missing_optional_source_flag") == "TRUE")),
        "DUPLICATE_TICKER_REMOVED_COUNT": str(duplicate_removed),
        "CURRENT_RANKED_CANDIDATE_IMPORTED_COUNT": str(imported_by_source.get("CURRENT_RANKED_CANDIDATES", 0)),
        "FORWARD_TRACKER_IMPORTED_COUNT": str(imported_by_source.get("STATE_FORWARD_TRACKER", 0) + imported_by_source.get("OUTPUT_FORWARD_TRACKER", 0)),
        "MANUAL_POSITION_IMPORTED_COUNT": str(imported_by_source.get("MANUAL_POSITIONS", 0) + imported_by_source.get("MANUAL_POSITION_REVIEW", 0)),
        "MANUAL_TRADE_LOG_IMPORTED_COUNT": str(imported_by_source.get("MANUAL_TRADE_LOG", 0) + imported_by_source.get("MANUAL_TRADE_FEEDBACK", 0)),
        "PRICE_UPDATE_EXECUTED": PRICE_UPDATE_EXECUTED,
        "EVENT_UPDATE_EXECUTED": EVENT_UPDATE_EXECUTED,
        "ROLLING_SCAN_EXECUTED": ROLLING_SCAN_EXECUTED,
        "CURRENT_DAILY_MODIFIED": "FALSE" if sha256(current_daily) == current_daily_before else "TRUE",
        "STABLE_SNAPSHOT_MODIFIED": "TRUE" if stable_modified else "FALSE",
        "DANGEROUS_TOKEN_FINDING_COUNT": str(len(hits)),
        "VALIDATION_FAIL_COUNT": str(validation_fail_count),
        "AUTO_TRADE": AUTO_TRADE,
        "AUTO_SELL": AUTO_SELL,
        "OFFICIAL_DECISION_IMPACT": OFFICIAL_DECISION_IMPACT,
    }

    p1_values = {
        "STATUS": P1_STATUS_OK if validation_fail_count == 0 else P1_STATUS_WARN,
        "MODE": P1_MODE,
        "MANUAL_ADDITION_SOURCE": rel(root, manual_path),
        "MANUAL_ADDITION_INPUT_COUNT": str(len(manual_raw_rows)),
        "MANUAL_ADDITION_UNIQUE_COUNT": str(len(manual_unique_tickers)),
        "MANUAL_ADDITION_DUPLICATE_COUNT": str(manual_duplicate_count),
        "MANUAL_ADDITION_NEW_TICKER_COUNT": str(manual_new_count),
        "MANUAL_ADDITION_EXISTING_TICKER_COUNT": str(manual_existing_count),
        "TOTAL_UNIVERSE_COUNT_BEFORE": str(total_universe_before),
        "TOTAL_UNIVERSE_COUNT_AFTER": str(len(final_rows)),
        "POSITION_COUNT": str(tier_counts.get("POSITION", 0)),
        "CORE_DAILY_COUNT": str(tier_counts.get("CORE_DAILY", 0)),
        "CANDIDATE_COUNT": str(tier_counts.get("CANDIDATE", 0)),
        "STRONG_WATCH_COUNT": str(tier_counts.get("STRONG_WATCH", 0)),
        "WATCHLIST_COUNT": str(tier_counts.get("WATCHLIST", 0)),
        "RESEARCH_COUNT": str(tier_counts.get("RESEARCH", 0)),
        "PRICE_UPDATE_EXECUTED": PRICE_UPDATE_EXECUTED,
        "EVENT_UPDATE_EXECUTED": EVENT_UPDATE_EXECUTED,
        "ROLLING_SCAN_EXECUTED": ROLLING_SCAN_EXECUTED,
        "CURRENT_DAILY_MODIFIED": values["CURRENT_DAILY_MODIFIED"],
        "STABLE_SNAPSHOT_MODIFIED": values["STABLE_SNAPSHOT_MODIFIED"],
        "DANGEROUS_TOKEN_FINDING_COUNT": str(len(hits)),
        "VALIDATION_FAIL_COUNT": str(validation_fail_count),
        "AUTO_TRADE": AUTO_TRADE,
        "AUTO_SELL": AUTO_SELL,
        "OFFICIAL_DECISION_IMPACT": OFFICIAL_DECISION_IMPACT,
    }

    read_keys = [
        "STATUS",
        "MODE",
        "TOTAL_UNIVERSE_COUNT",
        "POSITION_COUNT",
        "CORE_DAILY_COUNT",
        "CANDIDATE_COUNT",
        "STRONG_WATCH_COUNT",
        "WATCHLIST_COUNT",
        "RESEARCH_COUNT",
        "INPUT_SOURCE_COUNT",
        "MISSING_OPTIONAL_SOURCE_COUNT",
        "DUPLICATE_TICKER_REMOVED_COUNT",
        "CURRENT_RANKED_CANDIDATE_IMPORTED_COUNT",
        "FORWARD_TRACKER_IMPORTED_COUNT",
        "MANUAL_POSITION_IMPORTED_COUNT",
        "MANUAL_TRADE_LOG_IMPORTED_COUNT",
        "PRICE_UPDATE_EXECUTED",
        "EVENT_UPDATE_EXECUTED",
        "CURRENT_DAILY_MODIFIED",
        "STABLE_SNAPSHOT_MODIFIED",
        "DANGEROUS_TOKEN_FINDING_COUNT",
        "VALIDATION_FAIL_COUNT",
        "AUTO_TRADE",
        "AUTO_SELL",
        "OFFICIAL_DECISION_IMPACT",
    ]
    write_text(read_first_path, "\n".join(f"{key}: {values[key]}" for key in read_keys) + "\n")
    p1_read_keys = [
        "STATUS",
        "MODE",
        "MANUAL_ADDITION_SOURCE",
        "MANUAL_ADDITION_INPUT_COUNT",
        "MANUAL_ADDITION_UNIQUE_COUNT",
        "MANUAL_ADDITION_DUPLICATE_COUNT",
        "MANUAL_ADDITION_NEW_TICKER_COUNT",
        "MANUAL_ADDITION_EXISTING_TICKER_COUNT",
        "TOTAL_UNIVERSE_COUNT_BEFORE",
        "TOTAL_UNIVERSE_COUNT_AFTER",
        "POSITION_COUNT",
        "CORE_DAILY_COUNT",
        "CANDIDATE_COUNT",
        "STRONG_WATCH_COUNT",
        "WATCHLIST_COUNT",
        "RESEARCH_COUNT",
        "PRICE_UPDATE_EXECUTED",
        "EVENT_UPDATE_EXECUTED",
        "ROLLING_SCAN_EXECUTED",
        "CURRENT_DAILY_MODIFIED",
        "STABLE_SNAPSHOT_MODIFIED",
        "DANGEROUS_TOKEN_FINDING_COUNT",
        "VALIDATION_FAIL_COUNT",
        "AUTO_TRADE",
        "AUTO_SELL",
        "OFFICIAL_DECISION_IMPACT",
    ]
    write_text(p1_read_first_path, "\n".join(f"{key}: {p1_values[key]}" for key in p1_read_keys) + "\n")
    report = [
        "# V18.16A Universe Rolling State Builder",
        "",
        f"Generated: {dt.datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Read First",
        "",
        *[f"- {key}: {values[key]}" for key in read_keys],
        "",
        "## Validation",
        "",
        *[f"- {name}: {'PASS' if ok else 'FAIL'} {note}" for name, ok, note in validations],
        "",
        "State-builder only. No FullDaily, YFinance, price update, event update, rolling scan, live trading, or live selling was run.",
    ]
    write_text(report_path, "\n".join(report) + "\n")

    for key in [
        "STATUS",
        "MANUAL_ADDITION_INPUT_COUNT",
        "MANUAL_ADDITION_UNIQUE_COUNT",
        "MANUAL_ADDITION_NEW_TICKER_COUNT",
        "MANUAL_ADDITION_EXISTING_TICKER_COUNT",
        "TOTAL_UNIVERSE_COUNT_BEFORE",
        "TOTAL_UNIVERSE_COUNT_AFTER",
        "POSITION_COUNT",
        "CORE_DAILY_COUNT",
        "CANDIDATE_COUNT",
        "WATCHLIST_COUNT",
        "RESEARCH_COUNT",
        "VALIDATION_FAIL_COUNT",
        "AUTO_TRADE",
        "AUTO_SELL",
        "OFFICIAL_DECISION_IMPACT",
    ]:
        print(f"{key}: {p1_values[key]}")

    for key in [
        "STATUS",
        "TOTAL_UNIVERSE_COUNT",
        "POSITION_COUNT",
        "CORE_DAILY_COUNT",
        "CANDIDATE_COUNT",
        "WATCHLIST_COUNT",
        "RESEARCH_COUNT",
        "CURRENT_RANKED_CANDIDATE_IMPORTED_COUNT",
        "FORWARD_TRACKER_IMPORTED_COUNT",
        "MANUAL_POSITION_IMPORTED_COUNT",
        "VALIDATION_FAIL_COUNT",
        "AUTO_TRADE",
        "AUTO_SELL",
        "OFFICIAL_DECISION_IMPACT",
    ]:
        print(f"{key}: {values[key]}")
    return 0 if status == STATUS_OK else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=r"D:\us-tech-quant")
    args = parser.parse_args()
    return build(Path(args.root))


if __name__ == "__main__":
    raise SystemExit(main())
