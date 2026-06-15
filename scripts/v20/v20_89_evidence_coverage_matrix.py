#!/usr/bin/env python
"""V20.89 research-only evidence coverage matrix.

This stage aggregates evidence availability from prior V20 evidence exports.
It does not mutate rankings, scores, weights, recommendations, portfolios, or
trade actions.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STAGE = "V20.89"
VERSION = "V20_89"
OUTPUT_DIR = Path("outputs") / "v20" / "evidence_coverage"

CONTROLLED_STATUSES = {
    "USABLE",
    "PARTIAL",
    "MISSING",
    "BLOCKED",
    "NOT_APPLICABLE",
    "UNKNOWN",
}
FINAL_STATUSES = {
    "PASS_V20_89_EVIDENCE_COVERAGE_MATRIX_CREATED_WITH_PARTIAL_COVERAGE",
    "BLOCKED_V20_89_INSUFFICIENT_EVIDENCE_INPUTS",
}

FAMILIES = {
    "multi_path": {
        "label": "multi_path",
        "stage": "V20.82",
        "patterns": [
            "V20_CURRENT*MULTI*PATH*.csv",
            "V20_82*MULTI*PATH*.csv",
            "V20_CURRENT*STRATEGY*BENCHMARK*.csv",
            "V20_82*STRATEGY*BENCHMARK*.csv",
            "V20_CURRENT*MULTI*PATH*.json",
            "V20_82*MULTI*PATH*.json",
            "V20_CURRENT*MULTI*PATH*.md",
            "V20_82*MULTI*PATH*.md",
        ],
    },
    "etf_rotation": {
        "label": "etf_rotation",
        "stage": "V20.84",
        "patterns": [
            "V20_CURRENT*ETF*ROTATION*.csv",
            "V20_84*ETF*ROTATION*.csv",
            "V20_CURRENT*ETF*ROTATION*.json",
            "V20_84*ETF*ROTATION*.json",
            "V20_CURRENT*ETF*ROTATION*.md",
            "V20_84*ETF*ROTATION*.md",
        ],
    },
    "regime": {
        "label": "regime",
        "stage": "V20.86",
        "patterns": [
            "V20_CURRENT*REGIME*.csv",
            "V20_86*REGIME*.csv",
            "V20_CURRENT*REGIME*.json",
            "V20_86*REGIME*.json",
            "V20_CURRENT*REGIME*.md",
            "V20_86*REGIME*.md",
        ],
    },
    "downside_risk": {
        "label": "downside_risk",
        "stage": "V20.87",
        "patterns": [
            "V20_CURRENT*DOWNSIDE*.csv",
            "V20_87*DOWNSIDE*.csv",
            "V20_CURRENT*DOWNSIDE*.json",
            "V20_87*DOWNSIDE*.json",
            "V20_CURRENT*DOWNSIDE*.md",
            "V20_87*DOWNSIDE*.md",
        ],
    },
    "benchmark_comparison": {
        "label": "benchmark_comparison",
        "stage": "V20.88",
        "patterns": [
            "V20_CURRENT*BENCHMARK*COMPARISON*.csv",
            "V20_88*BENCHMARK*COMPARISON*.csv",
            "V20_CURRENT*BENCHMARK*COMPARISON*.json",
            "V20_88*BENCHMARK*COMPARISON*.json",
            "V20_CURRENT*BENCHMARK*.csv",
            "V20_88*BENCHMARK*.csv",
            "V20_CURRENT*BENCHMARK*.json",
            "V20_88*BENCHMARK*.json",
            "V20_CURRENT*BENCHMARK*.md",
            "V20_88*BENCHMARK*.md",
        ],
    },
}

CANDIDATE_PATTERNS = [
    "outputs/v20/**/V20_CURRENT*RANK*CANDIDATE*.csv",
    "outputs/v20/**/V20_CURRENT*CANDIDATE*.csv",
    "outputs/v20/**/V20_*RANK*CANDIDATE*.csv",
    "outputs/v18/**/V18_CURRENT*SIM*CANDIDATE*TRACKER.csv",
    "outputs/v18/**/V18_CURRENT*RANK*CANDIDATE*.csv",
    "state/v18/**/V18_CURRENT*SIM*CANDIDATE*TRACKER.csv",
]

ETF_TICKERS = {
    "QQQ",
    "SPY",
    "IWM",
    "DIA",
    "XLK",
    "XLF",
    "XLE",
    "XLV",
    "XLY",
    "XLI",
    "XLP",
    "XLU",
    "XLB",
    "XLRE",
    "SMH",
    "SOXX",
    "ARKK",
    "TQQQ",
    "SQQQ",
    "EEM",
    "EWZ",
    "EWY",
    "ARGT",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def run_id(now: datetime) -> str:
    return f"V20_89_{now.strftime('%Y%m%dT%H%M%SZ')}"


def is_current_alias(path: Path) -> bool:
    return "CURRENT" in path.name.upper()


def discover_by_patterns(patterns: list[str]) -> Path | None:
    matches: list[Path] = []
    for pattern in patterns:
        matches.extend(Path(".").glob(pattern))
    files = [p for p in matches if p.is_file()]
    if not files:
        return None
    files.sort(key=lambda p: (not is_current_alias(p), -p.stat().st_mtime))
    return files[0]


def normalize_status(value: Any, has_ticker_row: bool = True) -> str:
    if not has_ticker_row:
        return "MISSING"
    if value is None:
        return "UNKNOWN"
    text = str(value).strip().upper()
    if not text:
        return "UNKNOWN"
    if "NOT_APPLICABLE" in text or text in {"N/A", "NA", "NOT APPLICABLE"}:
        return "NOT_APPLICABLE"
    if any(token in text for token in ["BLOCK", "FAIL", "INSUFFICIENT"]):
        return "BLOCKED"
    if any(token in text for token in ["MISSING", "UNAVAILABLE", "NO_DATA", "NOT_AVAILABLE"]):
        return "MISSING"
    if "PARTIAL" in text:
        return "PARTIAL"
    if any(token in text for token in ["USABLE", "PASS", "READY", "EXPORTED", "VALID"]):
        return "USABLE"
    if text in CONTROLLED_STATUSES:
        return text
    return "UNKNOWN"


def usable_from_status(status: str) -> bool:
    return status in {"USABLE", "PARTIAL"}


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def extract_status_from_text(text: str) -> str:
    known = [
        "BLOCKED_V20_82_INSUFFICIENT_MULTI_PATH_EVIDENCE",
        "PARTIAL_BLOCK_MISSING_REQUIRED_PATHS",
        "PASS_V20_86_REGIME_CONDITIONED_EVIDENCE_EXPORTED_WITH_PARTIAL_COVERAGE",
        "PASS_V20_87_DOWNSIDE_RISK_EVIDENCE_EXPORTED_WITH_PARTIAL_COVERAGE",
        "PASS_V20_88_BENCHMARK_COMPARISON_EVIDENCE_EXPORTED_WITH_PARTIAL_COVERAGE",
    ]
    upper = text.upper()
    for status in known:
        if status in upper:
            return status
    match = re.search(r"\b(?:PASS|BLOCKED|PARTIAL_BLOCK|FAIL)_[A-Z0-9_]+", upper)
    if match:
        return match.group(0)
    return ""


def status_columns(fieldnames: list[str]) -> list[str]:
    candidates = []
    for name in fieldnames:
        lower = name.lower()
        if "status" in lower or "usable" in lower or "coverage" in lower or "eligib" in lower:
            candidates.append(name)
    return candidates


def ticker_value(row: dict[str, Any]) -> str:
    for key, value in row.items():
        if key and key.lower() in {"ticker", "symbol", "asset", "etf", "security"}:
            text = str(value).strip().upper()
            if re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", text):
                return text
    return ""


def load_family(family: str, path: Path | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "family": family,
        "path": str(path) if path else "",
        "found": bool(path),
        "global_status": "MISSING",
        "ticker_status": {},
        "tickers": set(),
        "detected_statuses": [],
    }
    if path is None:
        return result

    try:
        suffix = path.suffix.lower()
        if suffix == ".csv":
            rows = read_csv_rows(path)
            fieldnames = list(rows[0].keys()) if rows else []
            cols = status_columns(fieldnames)
            detected = []
            for row in rows:
                ticker = ticker_value(row)
                raw_status = ""
                for col in cols:
                    raw_status = row.get(col, "")
                    normalized = normalize_status(raw_status)
                    if normalized != "UNKNOWN":
                        break
                if ticker:
                    result["tickers"].add(ticker)
                    result["ticker_status"][ticker] = normalize_status(raw_status)
                if raw_status:
                    detected.append(str(raw_status))
            result["detected_statuses"] = sorted(set(detected))[:20]
            result["global_status"] = aggregate_status(result["ticker_status"].values())
        elif suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            text = json.dumps(data, sort_keys=True)
            detected_status = extract_status_from_text(text)
            result["global_status"] = normalize_status(detected_status or data.get("final_status") if isinstance(data, dict) else "")
            result["detected_statuses"] = [detected_status] if detected_status else []
            for row in iter_dicts(data):
                ticker = ticker_value(row)
                if not ticker:
                    continue
                raw_status = row.get("status") or row.get("evidence_status") or row.get("final_status")
                result["tickers"].add(ticker)
                result["ticker_status"][ticker] = normalize_status(raw_status)
        else:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            detected_status = extract_status_from_text(text)
            result["global_status"] = normalize_status(detected_status)
            result["detected_statuses"] = [detected_status] if detected_status else []
    except Exception as exc:  # pragma: no cover - defensive audit path
        result["global_status"] = "UNKNOWN"
        result["detected_statuses"] = [f"READ_ERROR: {exc}"]
    return result


def iter_dicts(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        found.append(value)
        for child in value.values():
            found.extend(iter_dicts(child))
    elif isinstance(value, list):
        for item in value:
            found.extend(iter_dicts(item))
    return found


def aggregate_status(statuses: Any) -> str:
    values = list(statuses)
    if not values:
        return "UNKNOWN"
    if any(s == "USABLE" for s in values):
        return "USABLE"
    if any(s == "PARTIAL" for s in values):
        return "PARTIAL"
    if any(s == "BLOCKED" for s in values):
        return "BLOCKED"
    if any(s == "MISSING" for s in values):
        return "MISSING"
    if any(s == "NOT_APPLICABLE" for s in values):
        return "NOT_APPLICABLE"
    return "UNKNOWN"


def load_universe() -> tuple[list[str], str, set[str]]:
    path = discover_by_patterns(CANDIDATE_PATTERNS)
    if not path:
        return [], "NO_CANDIDATE_UNIVERSE_FOUND", set()
    tickers: set[str] = set()
    for row in read_csv_rows(path):
        ticker = ticker_value(row)
        if ticker:
            tickers.add(ticker)
    return sorted(tickers), str(path), tickers


def coverage_tier(ratio: float, usable_count: int) -> str:
    if usable_count <= 0:
        return "NO_USABLE_COVERAGE"
    if ratio >= 1.0:
        return "FULL_COVERAGE"
    if ratio >= 0.75:
        return "HIGH_PARTIAL_COVERAGE"
    if ratio >= 0.5:
        return "PARTIAL_COVERAGE"
    return "LOW_COVERAGE"


def is_etf_ticker(ticker: str, etf_bound_tickers: set[str]) -> bool:
    return ticker in ETF_TICKERS or ticker in etf_bound_tickers


def build_outputs() -> dict[str, Any]:
    now = utc_now()
    this_run_id = run_id(now)
    generated_at = now.isoformat().replace("+00:00", "Z")

    discovered: dict[str, Path | None] = {}
    families: dict[str, dict[str, Any]] = {}
    for family, spec in FAMILIES.items():
        path = discover_by_patterns([f"outputs/v20/**/{p}" for p in spec["patterns"]])
        discovered[family] = path
        families[family] = load_family(family, path)

    universe, universe_source, base_candidates = load_universe()
    evidence_tickers = sorted({t for info in families.values() for t in info["tickers"]})
    tickers = sorted(set(universe) | set(evidence_tickers))

    if not tickers:
        final_status = "BLOCKED_V20_89_INSUFFICIENT_EVIDENCE_INPUTS"
    else:
        final_status = "PASS_V20_89_EVIDENCE_COVERAGE_MATRIX_CREATED_WITH_PARTIAL_COVERAGE"

    matrix_rows: list[dict[str, Any]] = []
    gap_rows: list[dict[str, Any]] = []
    etf_bound_tickers = set(families["etf_rotation"]["tickers"])

    for ticker in tickers:
        row: dict[str, Any] = {
            "ticker": ticker,
            "evidence_universe_source": universe_source if ticker in base_candidates else "UPSTREAM_EVIDENCE_ONLY",
            "base_candidate_present": str(ticker in base_candidates).upper(),
        }
        usable_required_count = 0
        required_count = 0
        gap_reasons: list[str] = []
        notes: list[str] = ["research_only_no_official_mutation"]

        for family in FAMILIES:
            status = family_status_for_ticker(family, ticker, families, etf_bound_tickers)
            row[f"{family}_evidence_status"] = status
            row[f"{family}_usable"] = str(usable_from_status(status)).upper()
            required_for_shadow = family_required_for_shadow(family, ticker, etf_bound_tickers)
            if required_for_shadow and status != "NOT_APPLICABLE":
                required_count += 1
                if usable_from_status(status):
                    usable_required_count += 1
            if status in {"MISSING", "BLOCKED", "PARTIAL", "UNKNOWN"}:
                reason = gap_reason_for_status(family, status, families[family])
                gap_reasons.append(f"{family}:{status}")
                gap_rows.append(
                    {
                        "ticker": ticker,
                        "evidence_family": family,
                        "gap_status": status,
                        "required_for_shadow": str(required_for_shadow).upper(),
                        "required_for_official": str(family != "etf_rotation").upper(),
                        "upstream_source": families[family]["path"] or "MISSING_INPUT",
                        "gap_reason": reason,
                        "recommended_next_action": recommended_next_action(family, status),
                    }
                )

        ratio = usable_required_count / required_count if required_count else 0.0
        tier = coverage_tier(ratio, usable_required_count)
        multi_path_status = row["multi_path_evidence_status"]
        shadow_eligible = (
            ratio >= 0.75
            and usable_from_status(multi_path_status)
            and row["downside_risk_evidence_status"] in {"USABLE", "PARTIAL"}
            and row["benchmark_comparison_evidence_status"] in {"USABLE", "PARTIAL"}
        )
        blocking_reason = build_blocking_reason(row, ratio)

        row.update(
            {
                "usable_evidence_family_count": usable_required_count,
                "required_evidence_family_count": required_count,
                "evidence_coverage_ratio": f"{ratio:.4f}",
                "evidence_coverage_tier": tier,
                "shadow_ranking_eligible": str(shadow_eligible).upper(),
                "official_recommendation_eligible": "FALSE",
                "blocking_reason": blocking_reason,
                "gap_reason": "; ".join(gap_reasons) if gap_reasons else "NO_REQUIRED_GAPS",
                "notes": "; ".join(notes),
            }
        )
        matrix_rows.append(row)

    summary_row = build_summary(this_run_id, generated_at, matrix_rows, final_status)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = output_paths()
    write_csv(paths["matrix"], matrix_rows, matrix_columns())
    write_csv(paths["summary"], [summary_row], list(summary_row.keys()))
    write_csv(paths["gap_table"], gap_rows, gap_columns())
    report_text = build_report(this_run_id, generated_at, matrix_rows, gap_rows, families, final_status)
    paths["report"].write_text(report_text, encoding="utf-8")

    manifest = build_manifest(
        this_run_id,
        generated_at,
        families,
        paths,
        matrix_rows,
        gap_rows,
        final_status,
    )
    paths["manifest"].write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    create_aliases(paths)

    return {
        "run_id": this_run_id,
        "final_status": final_status,
        "ticker_count": len(matrix_rows),
        "shadow_eligible_count": sum(1 for r in matrix_rows if r["shadow_ranking_eligible"] == "TRUE"),
        "official_eligible_count": sum(1 for r in matrix_rows if r["official_recommendation_eligible"] == "TRUE"),
        "output_dir": str(OUTPUT_DIR),
        "most_common_blocking_reasons": Counter(r["blocking_reason"] for r in matrix_rows).most_common(5),
    }


def family_status_for_ticker(
    family: str,
    ticker: str,
    families: dict[str, dict[str, Any]],
    etf_bound_tickers: set[str],
) -> str:
    if family == "etf_rotation" and not is_etf_ticker(ticker, etf_bound_tickers):
        return "NOT_APPLICABLE"
    info = families[family]
    if not info["found"]:
        return "MISSING"
    ticker_status = info["ticker_status"].get(ticker)
    if ticker_status:
        return ticker_status
    global_status = info["global_status"]
    if info["tickers"]:
        return "MISSING"
    return global_status if global_status in CONTROLLED_STATUSES else "UNKNOWN"


def family_required_for_shadow(family: str, ticker: str, etf_bound_tickers: set[str]) -> bool:
    if family == "etf_rotation":
        return is_etf_ticker(ticker, etf_bound_tickers)
    return True


def gap_reason_for_status(family: str, status: str, info: dict[str, Any]) -> str:
    if status == "MISSING" and not info["found"]:
        return f"{family} upstream input was not discovered"
    if status == "MISSING":
        return f"{family} has no ticker-level row for this ticker"
    if status == "BLOCKED":
        return f"{family} upstream evidence is blocked"
    if status == "PARTIAL":
        return f"{family} evidence exists but is only partial"
    if status == "UNKNOWN":
        return f"{family} evidence status could not be normalized"
    return f"{family} gap requires review"


def recommended_next_action(family: str, status: str) -> str:
    if status == "PARTIAL":
        return f"Complete missing ticker-level {family} evidence fields"
    if status == "BLOCKED":
        return f"Resolve upstream {family} block before promotion"
    if status == "UNKNOWN":
        return f"Export controlled status vocabulary for {family}"
    return f"Generate or link current {family} evidence export"


def build_blocking_reason(row: dict[str, Any], ratio: float) -> str:
    if row["multi_path_evidence_status"] == "BLOCKED":
        return "MULTI_PATH_EVIDENCE_BLOCKED"
    if row["multi_path_evidence_status"] == "MISSING":
        return "MISSING_MULTI_PATH_EVIDENCE"
    missing_required = [
        family
        for family in ["regime", "downside_risk", "benchmark_comparison"]
        if row[f"{family}_evidence_status"] in {"MISSING", "BLOCKED", "UNKNOWN"}
    ]
    if missing_required:
        return "MISSING_REQUIRED_EVIDENCE:" + "|".join(missing_required)
    if ratio < 0.75:
        return "INSUFFICIENT_SHADOW_COVERAGE_RATIO"
    return "OFFICIAL_RECOMMENDATION_DISABLED_BY_V20_89_RESEARCH_POLICY"


def build_summary(
    run_id_value: str,
    generated_at: str,
    matrix_rows: list[dict[str, Any]],
    final_status: str,
) -> dict[str, Any]:
    tier_counts = Counter(row["evidence_coverage_tier"] for row in matrix_rows)
    return {
        "run_id": run_id_value,
        "generated_at_utc": generated_at,
        "ticker_count": len(matrix_rows),
        "full_coverage_count": tier_counts["FULL_COVERAGE"],
        "high_partial_coverage_count": tier_counts["HIGH_PARTIAL_COVERAGE"],
        "partial_coverage_count": tier_counts["PARTIAL_COVERAGE"],
        "low_coverage_count": tier_counts["LOW_COVERAGE"],
        "no_usable_coverage_count": tier_counts["NO_USABLE_COVERAGE"],
        "shadow_ranking_eligible_count": sum(1 for r in matrix_rows if r["shadow_ranking_eligible"] == "TRUE"),
        "official_recommendation_eligible_count": sum(
            1 for r in matrix_rows if r["official_recommendation_eligible"] == "TRUE"
        ),
        "missing_multi_path_count": count_family_status(matrix_rows, "multi_path", "MISSING"),
        "missing_regime_count": count_family_status(matrix_rows, "regime", "MISSING"),
        "missing_downside_count": count_family_status(matrix_rows, "downside_risk", "MISSING"),
        "missing_benchmark_count": count_family_status(matrix_rows, "benchmark_comparison", "MISSING"),
        "missing_etf_rotation_count": count_family_status(matrix_rows, "etf_rotation", "MISSING"),
        "final_status": final_status,
    }


def count_family_status(rows: list[dict[str, Any]], family: str, status: str) -> int:
    return sum(1 for row in rows if row[f"{family}_evidence_status"] == status)


def build_report(
    run_id_value: str,
    generated_at: str,
    matrix_rows: list[dict[str, Any]],
    gap_rows: list[dict[str, Any]],
    families: dict[str, dict[str, Any]],
    final_status: str,
) -> str:
    family_counts = {
        family: Counter(row[f"{family}_evidence_status"] for row in matrix_rows)
        for family in FAMILIES
    }
    best = sorted(
        family_counts.items(),
        key=lambda item: (item[1]["USABLE"] + item[1]["PARTIAL"], item[0]),
        reverse=True,
    )
    blockers = Counter(row["evidence_family"] for row in gap_rows if row["required_for_official"] == "TRUE")
    ready_v20_90 = (
        "NO - score freshness / ranking delta audit should wait for required evidence gaps"
        if blockers
        else "YES - research coverage layer has no required family blockers"
    )
    lines = [
        "# V20.89 Evidence Coverage Matrix",
        "",
        f"- run_id: {run_id_value}",
        f"- generated_at_utc: {generated_at}",
        f"- final_status: {final_status}",
        "",
        "V20.89 is research-only. It creates no official recommendation and does not mutate ranking, score, weight, portfolio, or trade-action state.",
        "",
        "## Coverage",
        "",
    ]
    for family, counts in best:
        lines.append(
            f"- {family}: USABLE={counts['USABLE']}, PARTIAL={counts['PARTIAL']}, "
            f"MISSING={counts['MISSING']}, BLOCKED={counts['BLOCKED']}, "
            f"NOT_APPLICABLE={counts['NOT_APPLICABLE']}, UNKNOWN={counts['UNKNOWN']}"
        )
    lines.extend(["", "## Promotion Blockers", ""])
    if blockers:
        for family, count in blockers.most_common():
            lines.append(f"- {family}: {count} ticker gaps")
    else:
        lines.append("- No required family blockers detected.")
    lines.extend(
        [
            "",
            "## V20.90 Readiness",
            "",
            f"- Ready for V20.90 score freshness / ranking delta audit: {ready_v20_90}",
            "",
            "## Inputs",
            "",
        ]
    )
    for family, info in families.items():
        lines.append(f"- {family}: {info['path'] or 'MISSING'}")
    lines.extend(["", f"Final status: {final_status}", ""])
    return "\n".join(lines)


def build_manifest(
    run_id_value: str,
    generated_at: str,
    families: dict[str, dict[str, Any]],
    paths: dict[str, Path],
    matrix_rows: list[dict[str, Any]],
    gap_rows: list[dict[str, Any]],
    final_status: str,
) -> dict[str, Any]:
    found = {family: info["path"] for family, info in families.items() if info["found"]}
    missing = {
        family: FAMILIES[family]["patterns"]
        for family, info in families.items()
        if not info["found"]
    }
    upstream_statuses = {
        family: {
            "global_status": info["global_status"],
            "detected_statuses": info["detected_statuses"],
        }
        for family, info in families.items()
    }
    return {
        "stage": STAGE,
        "version": VERSION,
        "run_id": run_id_value,
        "generated_at_utc": generated_at,
        "input_files_found": found,
        "input_files_missing": missing,
        "output_files": {name: str(path) for name, path in paths.items()},
        "row_counts": {
            "matrix": len(matrix_rows),
            "gap_table": len(gap_rows),
            "summary": 1,
        },
        "upstream_statuses_detected": upstream_statuses,
        "policy_guards": [
            "research_only",
            "official_recommendation_eligible_always_false",
            "no_ranking_mutation",
            "no_score_mutation",
            "no_weight_mutation",
            "no_portfolio_mutation",
            "no_trade_action_output",
            "no_broker_api_calls",
            "no_future_data",
        ],
        "final_status": final_status,
    }


def output_paths() -> dict[str, Path]:
    return {
        "matrix": OUTPUT_DIR / "V20_89_EVIDENCE_COVERAGE_MATRIX.csv",
        "summary": OUTPUT_DIR / "V20_89_EVIDENCE_COVERAGE_SUMMARY.csv",
        "gap_table": OUTPUT_DIR / "V20_89_EVIDENCE_COVERAGE_GAP_TABLE.csv",
        "report": OUTPUT_DIR / "V20_89_EVIDENCE_COVERAGE_REPORT.md",
        "manifest": OUTPUT_DIR / "V20_89_EVIDENCE_COVERAGE_MANIFEST.json",
    }


def alias_paths() -> dict[str, Path]:
    return {
        "matrix": OUTPUT_DIR / "V20_CURRENT_EVIDENCE_COVERAGE_MATRIX.csv",
        "summary": OUTPUT_DIR / "V20_CURRENT_EVIDENCE_COVERAGE_SUMMARY.csv",
        "gap_table": OUTPUT_DIR / "V20_CURRENT_EVIDENCE_COVERAGE_GAP_TABLE.csv",
        "report": OUTPUT_DIR / "V20_CURRENT_EVIDENCE_COVERAGE_REPORT.md",
        "manifest": OUTPUT_DIR / "V20_CURRENT_EVIDENCE_COVERAGE_MANIFEST.json",
    }


def create_aliases(paths: dict[str, Path]) -> None:
    for name, alias in alias_paths().items():
        shutil.copyfile(paths[name], alias)


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def matrix_columns() -> list[str]:
    return [
        "ticker",
        "evidence_universe_source",
        "base_candidate_present",
        "multi_path_evidence_status",
        "multi_path_usable",
        "etf_rotation_evidence_status",
        "etf_rotation_usable",
        "regime_evidence_status",
        "regime_usable",
        "downside_risk_evidence_status",
        "downside_risk_usable",
        "benchmark_comparison_evidence_status",
        "benchmark_comparison_usable",
        "usable_evidence_family_count",
        "required_evidence_family_count",
        "evidence_coverage_ratio",
        "evidence_coverage_tier",
        "shadow_ranking_eligible",
        "official_recommendation_eligible",
        "blocking_reason",
        "gap_reason",
        "notes",
    ]


def gap_columns() -> list[str]:
    return [
        "ticker",
        "evidence_family",
        "gap_status",
        "required_for_shadow",
        "required_for_official",
        "upstream_source",
        "gap_reason",
        "recommended_next_action",
    ]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    result = build_outputs()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["final_status"] in FINAL_STATUSES else 1


if __name__ == "__main__":
    raise SystemExit(main())
