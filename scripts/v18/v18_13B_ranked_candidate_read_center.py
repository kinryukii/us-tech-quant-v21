from __future__ import annotations

import argparse
import csv
import math
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


ROOT_DEFAULT = Path(r"D:\us-tech-quant")

STATUS_OK = "OK_V18_13B_RANKED_CANDIDATE_READ_CENTER_READY"
STATUS_WARN_NO_SCORE = "WARN_V18_13B_NO_SCORE_SOURCE_FOUND"
STATUS_WARN_PARTIAL = "WARN_V18_13B_PARTIAL_RANK_READY"
STATUS_WARN_FALLBACK = "WARN_V18_13B_FALLBACK_RANK_READY"
STATUS_FAIL_DANGEROUS = "FAIL_V18_13B_DANGEROUS_TOKEN_FOUND"

RANK_SOURCE_OK = "OK_SCORE_SOURCE_FOUND"
RANK_SOURCE_NO_SCORE = "NO_SCORE_SOURCE_FOUND"
RANK_SOURCE_PARTIAL = "PARTIAL_SCORE_SOURCE_FOUND"
RANK_SOURCE_FALLBACK = "FALLBACK_SCORE_SOURCE_USED"

OFFICIAL_DECISION_IMPACT = "NONE"
AUTO_TRADE = "DISABLED"
AUTO_SELL = "DISABLED"
READ_ONLY = "TRUE"

FINAL_REVIEW = "REVIEW_ONLY"
FINAL_WAIT_PULLBACK = "WAIT_PULLBACK_REVIEW_ONLY"
FINAL_NO_TRADE = "NO_TRADE_REVIEW_ONLY"
FINAL_NO_RANK = "REVIEW_ONLY_NO_RANK"
FINAL_PARTIAL_RANK = "REVIEW_ONLY_PARTIAL_RANK"

RANKING_POLICY_PRIMARY = "PRIMARY_CURRENT_ONLY"
RANKING_POLICY_FALLBACK = "FALLBACK_AUDIT_ONLY"

DANGEROUS_TOKENS = (
    "BUY_NOW",
    "SELL_NOW",
    "EXECUTE_ORDER",
    "PLACE_ORDER",
    "AUTO_TRADE: ENABLED",
    "AUTO_SELL: ENABLED",
)

TICKER_COLUMNS = ("ticker", "symbol", "Ticker", "SYMBOL")
SCORE_COLUMNS = (
    "final_score",
    "composite_score",
    "factor_score",
    "factor_pack_score",
    "technical_score",
    "technical_timing_score",
    "momentum_score",
    "relative_strength_score",
    "trend_score",
    "quality_score",
    "value_score",
    "priority",
    "shadow_score",
    "official_score",
)
STRONG_SCORE_COLUMNS = ("final_score", "composite_score")
RANK_COLUMNS = ("rank", "shadow_rank", "priority_rank", "candidate_rank", "factor_pack_rank")
STATUS_COLUMNS = (
    "final_action",
    "action",
    "signal",
    "status",
    "technical_status",
    "event_risk_status",
    "overheat_status",
    "pullback_status",
    "execution_status",
    "lifecycle_stage",
    "label",
)
PENALTY_HINTS = ("penalty", "risk_penalty", "overheat_penalty")

SCAN_DIRS = (
    "outputs/v18/daily_integrated",
    "outputs/v18/factor_pack",
    "outputs/v18/factor_audit",
    "outputs/v18/promotion_merge",
    "outputs/v18/technical_timing",
    "outputs/v18/technical_timing_backtest",
    "outputs/v18/sell_timing",
    "outputs/v18/read_center",
    "outputs/v18/shadow_research",
    "outputs/v18/decision",
    "outputs/v17/price",
)

PRICE_INPUTS = (
    "outputs/v17/price/v17_6E_screened_universe_latest_prices.csv",
    "state/v17_6E_screened_universe_latest_price_snapshot.csv",
)

CANDIDATE_FIELDS = [
    "rank",
    "ticker",
    "composite_candidate_score",
    "ranking_source_policy",
    "primary_score_source_files",
    "audit_only_source_files",
    "score_source_status",
    "score_source_files",
    "score_source_columns",
    "latest_price_date",
    "latest_close",
    "technical_status",
    "event_risk_status",
    "overheat_status",
    "pullback_status",
    "execution_status",
    "final_action",
    "reason",
]

AUDIT_FIELDS = [
    "input_path",
    "exists",
    "file_type",
    "source_family",
    "source_role",
    "row_count",
    "ticker_column_found",
    "score_columns_found",
    "status_columns_found",
    "selected_for_ranking",
    "exclusion_reason",
    "note",
]


@dataclass
class CandidateEvidence:
    ticker: str
    strong_scores: List[float] = field(default_factory=list)
    factor_scores: List[float] = field(default_factory=list)
    technical_scores: List[float] = field(default_factory=list)
    momentum_scores: List[float] = field(default_factory=list)
    secondary_scores: List[float] = field(default_factory=list)
    penalty_scores: List[float] = field(default_factory=list)
    ranks: List[float] = field(default_factory=list)
    files: set[str] = field(default_factory=set)
    columns: set[str] = field(default_factory=set)
    latest_price_date: str = ""
    latest_close: str = ""
    technical_status: str = ""
    event_risk_status: str = ""
    overheat_status: str = ""
    pullback_status: str = ""
    execution_status: str = ""


@dataclass(frozen=True)
class SourceSpec:
    path: str
    source_family: str
    source_role: str
    family_key: str
    precedence: int = 0


@dataclass
class ScanResult:
    status: str
    rank_source_status: str
    ranking_source_policy: str
    primary_score_source_files: List[str]
    audit_only_source_files: List[str]
    fallback_used: bool
    selected_source_files: List[str]
    strong_mode: bool


@dataclass
class SourceRecord:
    path: Path
    rel_path: str
    spec: SourceSpec
    exists: bool
    file_type: str
    row_count: int
    ticker_col: str
    score_cols: List[str]
    status_cols: List[str]
    rank_cols: List[str]
    penalty_cols: List[str]
    parse_status: str
    rows: List[Dict[str, str]]
    fields: List[str]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp932"):
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def read_csv(path: Path) -> Tuple[List[Dict[str, str]], List[str], str]:
    for enc in ("utf-8-sig", "utf-8", "cp932"):
        try:
            with path.open("r", encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                return list(reader), list(reader.fieldnames or []), "OK"
        except Exception:
            continue
    return [], [], "CSV_PARSE_FAILED"


def write_csv(path: Path, rows: List[Dict[str, object]], fields: Sequence[str]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


def rel_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except Exception:
        return str(path)


def to_float(value: object) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        val = float(text)
    except ValueError:
        return None
    if math.isnan(val) or math.isinf(val):
        return None
    return val


def first_existing_column(fields: Sequence[str], candidates: Sequence[str]) -> str:
    field_set = set(fields)
    for col in candidates:
        if col in field_set:
            return col
    lower_map = {c.lower(): c for c in fields}
    for col in candidates:
        hit = lower_map.get(col.lower())
        if hit:
            return hit
    return ""


def matching_columns(fields: Sequence[str], candidates: Sequence[str]) -> List[str]:
    lower_candidates = {c.lower() for c in candidates}
    return [c for c in fields if c in candidates or c.lower() in lower_candidates]


def rel_norm(root: Path, path: Path) -> str:
    return rel_path(root, path).replace("\\", "/")


def current_output_files(root: Path) -> List[Path]:
    paths: List[Path] = []
    for item in SCAN_DIRS:
        scan_root = root / item
        if not scan_root.exists():
            continue
        for path in scan_root.glob("*"):
            if path.is_file() and path.suffix.lower() in (".csv", ".md"):
                name = path.name.lower()
                if "current" in name or "latest" in name:
                    paths.append(path)
    return sorted(paths, key=lambda p: rel_path(root, p).lower())


def classify_source(root: Path, path: Path) -> SourceSpec:
    rel = rel_norm(root, path)
    if rel == "outputs/v18/factor_pack/V18_CURRENT_RAW105_FACTOR_PACK_RANKING.csv":
        return SourceSpec(rel, "factor_pack_current_primary", "primary", "factor_pack", 0)
    if rel == "outputs/v18/factor_pack/V18_CURRENT_RAW105_FACTOR_PACK_VALUES.csv":
        return SourceSpec(rel, "factor_pack_current_values_audit", "audit_only", "factor_pack", 10)
    if rel == "outputs/v18/factor_pack/V18_3D_R2_CURRENT_RAW105_FACTOR_PACK_RANKING.csv":
        return SourceSpec(rel, "factor_pack_legacy_audit", "audit_only", "factor_pack", 20)
    if rel == "outputs/v18/factor_pack/V18_3D_R2_CURRENT_RAW105_FACTOR_PACK_VALUES.csv":
        return SourceSpec(rel, "factor_pack_legacy_audit", "audit_only", "factor_pack", 30)
    if rel == "outputs/v18/technical_timing/V18_6A_CURRENT_TECHNICAL_TIMING.csv":
        return SourceSpec(rel, "technical_timing_current_primary", "primary", "technical_timing", 0)
    if rel == "outputs/v18/technical_timing_backtest/V18_6B_CURRENT_TECHNICAL_TIMING_BACKTEST_DETAIL.csv":
        return SourceSpec(rel, "technical_timing_backtest_audit", "audit_only", "technical_timing", 10)
    if rel == "outputs/v18/technical_timing_backtest/V18_6B_R1_CURRENT_TECHNICAL_TIMING_DIAGNOSTIC_DETAIL.csv":
        return SourceSpec(rel, "technical_timing_backtest_audit", "audit_only", "technical_timing", 20)
    if rel.startswith("outputs/v17/price/") and path.suffix.lower() == ".csv":
        return SourceSpec(rel, "price_audit", "audit_only", "price", 0)
    return SourceSpec(rel, "other_audit", "audit_only", "other", 0)


def read_tickers(path: Path) -> List[str]:
    if not path.exists():
        raise FileNotFoundError(f"Missing second-stage universe: {path}")
    text = read_text(path)
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text) or {}
        values = data.get("tickers", []) if isinstance(data, dict) else []
        tickers = [str(x).strip().upper() for x in values if str(x).strip()]
        if tickers:
            return sorted(dict.fromkeys(tickers))
    except Exception:
        pass

    tickers: List[str] = []
    in_tickers = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == "tickers:":
            in_tickers = True
            continue
        if in_tickers and line.startswith("- "):
            tickers.append(line[2:].strip().strip("'\"").upper())
        elif in_tickers and not raw.startswith((" ", "\t")):
            break
    return sorted(dict.fromkeys(t for t in tickers if t))


def source_category(col: str) -> str:
    name = col.lower()
    if name in ("final_score", "composite_score"):
        return "strong"
    if name in ("factor_pack_score", "factor_score"):
        return "factor"
    if name in ("technical_timing_score", "technical_score"):
        return "technical"
    if name in ("momentum_score", "relative_strength_score", "trend_score"):
        return "momentum"
    if name in ("quality_score", "value_score", "shadow_score", "official_score", "priority"):
        return "secondary"
    return ""


def avg(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def compute_score(ev: CandidateEvidence, strong_mode: bool) -> Optional[float]:
    if strong_mode:
        return avg(ev.strong_scores)
    total = 0.0
    used = False
    category_weights = (
        (ev.factor_scores, 0.40),
        (ev.technical_scores, 0.30),
        (ev.momentum_scores, 0.20),
    )
    for values, weight in category_weights:
        value = avg(values)
        if value is not None:
            total += value * weight
            used = True
    secondary = avg(ev.secondary_scores)
    if secondary is not None:
        total += secondary * 0.10
        used = True
    penalty = avg([abs(x) for x in ev.penalty_scores])
    if penalty is not None:
        total -= penalty
        used = True
    return total if used else None


def update_price(ev: CandidateEvidence, row: Dict[str, str], fields: Sequence[str]) -> None:
    date_col = first_existing_column(fields, ("latest_price_date", "price_date", "date", "snapshot_date"))
    close_col = first_existing_column(fields, ("latest_close", "close", "current_price", "signal_price"))
    date_val = str(row.get(date_col, "")).strip() if date_col else ""
    close_val = str(row.get(close_col, "")).strip() if close_col else ""
    if date_val and (not ev.latest_price_date or date_val >= ev.latest_price_date):
        ev.latest_price_date = date_val
        if close_val:
            ev.latest_close = close_val
    elif close_val and not ev.latest_close:
        ev.latest_close = close_val


def set_statuses(ev: CandidateEvidence, row: Dict[str, str], fields: Sequence[str]) -> None:
    def take(attr: str, names: Sequence[str]) -> None:
        col = first_existing_column(fields, names)
        value = str(row.get(col, "")).strip() if col else ""
        if value and not getattr(ev, attr):
            setattr(ev, attr, value)

    take("technical_status", ("technical_status", "technical_signal", "technical_warning_label", "signal"))
    take("event_risk_status", ("event_risk_status", "event_exit_signal"))
    take("overheat_status", ("overheat_status", "overheat_exit_signal", "gamma_squeeze_risk_label"))
    take("pullback_status", ("pullback_status", "bb_status"))
    take("execution_status", ("execution_status", "fetch_status", "status"))


def safe_final_action(ev: CandidateEvidence, ranked_status: str, has_score: bool) -> str:
    if ranked_status == RANK_SOURCE_NO_SCORE:
        return FINAL_NO_RANK
    if ranked_status == RANK_SOURCE_PARTIAL and not has_score:
        return FINAL_PARTIAL_RANK
    status_text = " ".join(
        [
            ev.technical_status,
            ev.event_risk_status,
            ev.overheat_status,
            ev.pullback_status,
            ev.execution_status,
        ]
    ).upper()
    if any(token in status_text for token in ("AVOID", "RISK", "EXIT", "OVERHEAT", "NO_TRADE")):
        return FINAL_NO_TRADE
    if "PULLBACK" in status_text or "LOWER" in status_text or "WATCH" in status_text:
        return FINAL_WAIT_PULLBACK
    return FINAL_REVIEW


def score_reason(ev: CandidateEvidence, has_score: bool, ranked_status: str) -> str:
    if ranked_status == RANK_SOURCE_NO_SCORE:
        return "No usable score source found in current local outputs; alphabetical universe order retained."
    if not has_score:
        return "No ticker-level usable score found; placed after scored candidates alphabetically."
    cols = ", ".join(sorted(ev.columns))
    return f"Read-only ranking from local source columns: {cols}."


def load_price_inputs(root: Path, universe: set[str], evidence: Dict[str, CandidateEvidence], audit: List[Dict[str, object]]) -> None:
    for rel in PRICE_INPUTS:
        path = root / rel
        if not path.exists():
            spec = SourceSpec(rel, "price_audit", "audit_only", "price", 0)
            audit.append(audit_row(root, path, False, "csv", spec, 0, "", [], [], False, "Optional price input missing.", "Price context not available."))
            continue
        rows, fields, parse = read_csv(path)
        ticker_col = first_existing_column(fields, TICKER_COLUMNS)
        selected = parse == "OK" and bool(ticker_col)
        spec = classify_source(root, path)
        audit.append(
            audit_row(
                root,
                path,
                True,
                "csv",
                spec,
                len(rows),
                ticker_col,
                [],
                matching_columns(fields, STATUS_COLUMNS),
                False,
                "Price context loaded." if selected else parse,
                "Price inputs are audit-only and not used for ranking.",
            )
        )
        if not selected:
            continue
        for row in rows:
            ticker = str(row.get(ticker_col, "")).strip().upper()
            if ticker in universe:
                update_price(evidence[ticker], row, fields)


def audit_row(
    root: Path,
    path: Path,
    exists: bool,
    file_type: str,
    source_spec: SourceSpec,
    row_count: int,
    ticker_col: str,
    score_cols: Sequence[str],
    status_cols: Sequence[str],
    selected: bool,
    note: str,
    exclusion_reason: str,
) -> Dict[str, object]:
    return {
        "input_path": rel_path(root, path),
        "exists": "TRUE" if exists else "FALSE",
        "file_type": file_type,
        "source_family": source_spec.source_family,
        "source_role": source_spec.source_role,
        "row_count": row_count,
        "ticker_column_found": ticker_col,
        "score_columns_found": ";".join(score_cols),
        "status_columns_found": ";".join(status_cols),
        "selected_for_ranking": "TRUE" if selected else "FALSE",
        "exclusion_reason": exclusion_reason,
        "note": note,
    }


def scan_sources(root: Path, universe: set[str], evidence: Dict[str, CandidateEvidence], audit: List[Dict[str, object]]) -> ScanResult:
    records: List[SourceRecord] = []
    for path in current_output_files(root):
        spec = classify_source(root, path)
        file_type = path.suffix.lower().lstrip(".")
        exists = path.exists()
        if not exists:
            records.append(
                SourceRecord(path, spec.path, spec, False, file_type, 0, "", [], [], [], [], "MISSING", [], [])
            )
            audit.append(
                audit_row(
                    root,
                    path,
                    False,
                    file_type,
                    spec,
                    0,
                    "",
                    [],
                    [],
                    False,
                    "Source file missing.",
                    "Missing source file; not used for ranking.",
                )
            )
            continue
        if file_type != "csv":
            line_count = len(read_text(path).splitlines())
            records.append(SourceRecord(path, spec.path, spec, True, file_type, line_count, "", [], [], [], [], "OK", [], []))
            audit.append(
                audit_row(
                    root,
                    path,
                    True,
                    file_type,
                    spec,
                    line_count,
                    "",
                    [],
                    [],
                    False,
                    "Markdown read-center output audited; not selected for ticker ranking.",
                    "Markdown audit output.",
                )
            )
            continue
        rows, fields, parse = read_csv(path)
        ticker_col = first_existing_column(fields, TICKER_COLUMNS)
        score_cols = matching_columns(fields, SCORE_COLUMNS)
        rank_cols = matching_columns(fields, RANK_COLUMNS)
        status_cols = matching_columns(fields, STATUS_COLUMNS)
        penalty_cols = [c for c in fields if any(h in c.lower() for h in PENALTY_HINTS)]
        records.append(
            SourceRecord(
                path=path,
                rel_path=spec.path,
                spec=spec,
                exists=True,
                file_type=file_type,
                row_count=len(rows),
                ticker_col=ticker_col,
                score_cols=score_cols,
                status_cols=status_cols,
                rank_cols=rank_cols,
                penalty_cols=penalty_cols,
                parse_status=parse,
                rows=rows,
                fields=fields,
            )
        )

    family_primary_exists = {"factor_pack": False, "technical_timing": False}
    for rec in records:
        if rec.spec.family_key in family_primary_exists and rec.spec.source_family.endswith("_primary") and rec.parse_status == "OK" and rec.ticker_col and rec.score_cols:
            family_primary_exists[rec.spec.family_key] = True

    selected_rels: set[str] = set()
    selected_primary_files: List[str] = []
    selected_audit_only_files: List[str] = []
    fallback_used = False

    for family_key in ("factor_pack", "technical_timing"):
        family_records = [rec for rec in records if rec.spec.family_key == family_key and rec.parse_status == "OK" and rec.ticker_col and rec.score_cols]
        primary_records = [rec for rec in family_records if rec.spec.source_role == "primary"]
        if family_primary_exists[family_key] and primary_records:
            chosen = sorted(primary_records, key=lambda rec: rec.spec.precedence)[0]
            selected_rels.add(chosen.rel_path)
            selected_primary_files.append(chosen.rel_path)
            for rec in family_records:
                if rec.rel_path != chosen.rel_path:
                    selected_audit_only_files.append(rec.rel_path)
        elif family_records:
            fallback_used = True
            chosen = sorted(family_records, key=lambda rec: rec.spec.precedence)[0]
            selected_rels.add(chosen.rel_path)
            selected_audit_only_files.extend(rec.rel_path for rec in family_records if rec.rel_path != chosen.rel_path)
        # if there are no family_records or no usable score sources, leave unselected

    selected_audit_only_files = sorted(dict.fromkeys(selected_audit_only_files))
    selected_primary_files = sorted(dict.fromkeys(selected_primary_files))

    strong_mode = any(
        rec.rel_path in selected_rels and any(col.lower() in STRONG_SCORE_COLUMNS for col in rec.score_cols)
        for rec in records
    )

    for rec in records:
        if rec.file_type != "csv":
            continue
        selected = rec.rel_path in selected_rels and bool(rec.score_cols) and rec.parse_status == "OK" and bool(rec.ticker_col)
        actual_role = rec.spec.source_role
        if selected and rec.spec.source_role == "audit_only":
            actual_role = "fallback"
        exclusion_reason = ""
        if not selected:
            if rec.parse_status != "OK":
                exclusion_reason = "CSV parse failed."
            elif not rec.ticker_col:
                exclusion_reason = "Ticker column missing."
            elif rec.spec.family_key in ("factor_pack", "technical_timing"):
                if family_primary_exists[rec.spec.family_key] and rec.spec.source_role != "primary":
                    exclusion_reason = f"Primary current source exists for {rec.spec.family_key}; excluded from ranking to avoid duplication."
                elif rec.spec.source_role == "primary":
                    exclusion_reason = f"Primary source unavailable or unusable for {rec.spec.family_key}."
                else:
                    exclusion_reason = "Audit-only source."
            else:
                exclusion_reason = "Audit-only source."
        note = "Selected for read-only evidence scan." if selected else (rec.parse_status if rec.parse_status != "OK" else "No ticker-level score/rank/status columns.")
        audit.append(
            audit_row(
                root,
                rec.path,
                True,
                "csv",
                SourceSpec(rec.spec.path, rec.spec.source_family, actual_role, rec.spec.family_key, rec.spec.precedence),
                rec.row_count,
                rec.ticker_col,
                rec.score_cols,
                rec.status_cols,
                selected,
                note if selected else note,
                exclusion_reason,
            )
        )
        if not selected:
            continue
        for row in rec.rows:
            ticker = str(row.get(rec.ticker_col, "")).strip().upper()
            if ticker not in universe:
                continue
            ev = evidence[ticker]
            row_used = False
            for col in rec.score_cols:
                value = to_float(row.get(col))
                if value is None:
                    continue
                category = source_category(col)
                if category == "strong":
                    ev.strong_scores.append(value)
                elif category == "factor":
                    ev.factor_scores.append(value)
                elif category == "technical":
                    ev.technical_scores.append(value)
                elif category == "momentum":
                    ev.momentum_scores.append(value)
                elif category == "secondary":
                    ev.secondary_scores.append(value)
                else:
                    continue
                ev.columns.add(col)
                row_used = True
            for col in rec.rank_cols:
                value = to_float(row.get(col))
                if value is not None:
                    ev.ranks.append(value)
                    if row_used:
                        ev.columns.add(col)
            for col in rec.penalty_cols:
                value = to_float(row.get(col))
                if value is not None:
                    ev.penalty_scores.append(value)
                    ev.columns.add(col)
                    row_used = True
            if row_used:
                ev.files.add(rec.rel_path)
            update_price(ev, row, rec.fields)
            set_statuses(ev, row, rec.fields)

    if fallback_used:
        status = STATUS_WARN_FALLBACK
        rank_source_status = RANK_SOURCE_FALLBACK
    else:
        scored_any = any(compute_score(ev, strong_mode) is not None for ev in evidence.values())
        if not scored_any:
            status = STATUS_WARN_NO_SCORE
            rank_source_status = RANK_SOURCE_NO_SCORE
        else:
            # final status is reconciled after build_rows determines whether all candidates were scored
            status = STATUS_OK
            rank_source_status = RANK_SOURCE_OK

    return ScanResult(
        status=status,
        rank_source_status=rank_source_status,
        ranking_source_policy=RANKING_POLICY_FALLBACK if fallback_used else RANKING_POLICY_PRIMARY,
        primary_score_source_files=selected_primary_files,
        audit_only_source_files=selected_audit_only_files,
        fallback_used=fallback_used,
        selected_source_files=sorted(selected_rels),
        strong_mode=strong_mode,
    )


def load_yaml_audit(root: Path, path: Path, ticker_count: int) -> Dict[str, object]:
    spec = SourceSpec(rel_norm(root, path), "other_audit", "audit_only", "other", 0)
    return audit_row(
        root,
        path,
        path.exists(),
        "yaml",
        spec,
        ticker_count,
        "tickers",
        [],
        [],
        False,
        "Second-stage alphabetic universe loaded as candidate set; not treated as a rank.",
        "Universe config is stable and audit-only.",
    )


def build_rows(
    evidence: Dict[str, CandidateEvidence],
    scan_result: ScanResult,
) -> Tuple[List[Dict[str, object]], str, str, int, int]:
    scored: List[Tuple[str, float, float, CandidateEvidence]] = []
    unscored: List[CandidateEvidence] = []
    scores_by_ticker: Dict[str, float] = {}
    for ticker, ev in evidence.items():
        score = compute_score(ev, scan_result.strong_mode)
        if score is None:
            unscored.append(ev)
        else:
            scores_by_ticker[ticker] = score
            rank_tie = min(ev.ranks) if ev.ranks else 999999.0
            scored.append((ticker, score, rank_tie, ev))

    scored_count = len(scored)
    unscored_count = len(unscored)
    if scan_result.fallback_used:
        status = STATUS_WARN_FALLBACK
        rank_source_status = RANK_SOURCE_FALLBACK
    elif scored_count == 0:
        status = STATUS_WARN_NO_SCORE
        rank_source_status = RANK_SOURCE_NO_SCORE
    elif unscored_count > 0:
        status = STATUS_WARN_PARTIAL
        rank_source_status = RANK_SOURCE_PARTIAL
    else:
        status = STATUS_OK
        rank_source_status = RANK_SOURCE_OK

    rows: List[Dict[str, object]] = []
    ordered_scored = sorted(scored, key=lambda x: (-x[1], x[2], x[0]))
    ordered_unscored = sorted(unscored, key=lambda ev: ev.ticker)
    ordered = [ev for _, _, _, ev in ordered_scored] + ordered_unscored
    for idx, ev in enumerate(ordered, start=1):
        has_score = ev.ticker in scores_by_ticker
        score = scores_by_ticker.get(ev.ticker)
        rows.append(
            {
                "rank": idx,
                "ticker": ev.ticker,
                "composite_candidate_score": "" if score is None else f"{score:.6f}",
                "ranking_source_policy": scan_result.ranking_source_policy,
                "primary_score_source_files": ";".join(scan_result.primary_score_source_files),
                "audit_only_source_files": ";".join(scan_result.audit_only_source_files),
                "score_source_status": rank_source_status if has_score or rank_source_status == RANK_SOURCE_NO_SCORE else RANK_SOURCE_PARTIAL,
                "score_source_files": ";".join(sorted(ev.files)),
                "score_source_columns": ";".join(sorted(ev.columns)),
                "latest_price_date": ev.latest_price_date,
                "latest_close": ev.latest_close,
                "technical_status": ev.technical_status,
                "event_risk_status": ev.event_risk_status,
                "overheat_status": ev.overheat_status,
                "pullback_status": ev.pullback_status,
                "execution_status": ev.execution_status,
                "final_action": safe_final_action(ev, rank_source_status, has_score),
                "reason": score_reason(ev, has_score, rank_source_status),
            }
        )
    return rows, status, rank_source_status, scored_count, unscored_count


def markdown_table(rows: Sequence[Dict[str, object]], fields: Sequence[str]) -> List[str]:
    out = ["| " + " | ".join(fields) + " |", "| " + " | ".join(["---"] * len(fields)) + " |"]
    for row in rows:
        vals = [str(row.get(f, "")).replace("|", "/") for f in fields]
        out.append("| " + " | ".join(vals) + " |")
    return out


def make_read_center(
    rows: List[Dict[str, object]],
    audit: List[Dict[str, object]],
    scan_result: ScanResult,
    second_stage_count: int,
    scored_count: int,
    unscored_count: int,
) -> str:
    selected_count = sum(1 for r in audit if r.get("selected_for_ranking") == "TRUE")
    lines = [
        "# V18.13B Ranked Candidate Read Center",
        "",
        f"STATUS: {scan_result.status}",
        f"SECOND_STAGE_COUNT: {second_stage_count}",
        f"RANK_SOURCE_STATUS: {scan_result.rank_source_status}",
        f"SCORED_TICKER_COUNT: {scored_count}",
        f"UNSCORED_TICKER_COUNT: {unscored_count}",
        f"OFFICIAL_DECISION_IMPACT: {OFFICIAL_DECISION_IMPACT}",
        f"AUTO_TRADE: {AUTO_TRADE}",
        f"AUTO_SELL: {AUTO_SELL}",
        f"READ_ONLY: {READ_ONLY}",
        "",
        "## TOP_RANKED_CANDIDATES",
    ]
    top_fields = ["rank", "ticker", "composite_candidate_score", "final_action", "technical_status", "latest_price_date", "latest_close"]
    lines.extend(markdown_table(rows[:20], top_fields))
    lines.extend(
        [
            "",
            "## DATA_SOURCE_AUDIT",
            f"- scanned_input_count: {len(audit)}",
            f"- selected_for_ranking_count: {selected_count}",
            f"- ranking_source_files: {selected_count}",
            "",
            "## SOURCE_DEDUP_POLICY",
            f"- primary_files_used_for_ranking: {(';'.join(scan_result.primary_score_source_files) if scan_result.primary_score_source_files else 'NONE')}",
            f"- audit_only_files_excluded_from_ranking: {(';'.join(scan_result.audit_only_source_files) if scan_result.audit_only_source_files else 'NONE')}",
            f"- fallback_used: {'TRUE' if scan_result.fallback_used else 'FALSE'}",
            f"- ranking_source_policy: {scan_result.ranking_source_policy}",
            "",
            "## LIMITATIONS",
            "- The second-stage universe is treated only as a stable alphabetic candidate set, not as a rank.",
            "- Ranking uses existing local current outputs only; no network or yfinance calls are made.",
            "- This read center has no official decision impact and cannot create live trading behavior.",
        ]
    )
    return "\n".join(lines) + "\n"


def make_read_first(status: str, rank_source_status: str, second_stage_count: int, top5: str, read_center: Path, csv_path: Path, root: Path) -> str:
    return "\n".join(
        [
            f"STATUS: {status}",
            f"RANK_SOURCE_STATUS: {rank_source_status}",
            f"SECOND_STAGE_COUNT: {second_stage_count}",
            f"TOP_5_TICKERS: {top5}",
            f"OFFICIAL_DECISION_IMPACT: {OFFICIAL_DECISION_IMPACT}",
            f"AUTO_TRADE: {AUTO_TRADE}",
            f"AUTO_SELL: {AUTO_SELL}",
            f"READ_ONLY: {READ_ONLY}",
            f"READ_CENTER: {rel_path(root, read_center)}",
            f"CSV: {rel_path(root, csv_path)}",
            "",
        ]
    )


def dangerous_token_hits(paths: Sequence[Path]) -> List[str]:
    hits: List[str] = []
    for path in paths:
        text = read_text(path)
        for token in DANGEROUS_TOKENS:
            if token in text:
                hits.append(f"{path}:{token}")
    return hits


def run(root: Path) -> Dict[str, str]:
    universe_path = root / "configs/v16/universe/us_full_second_stage_generated.yaml"
    candidate_dir = root / "outputs/v18/candidates"
    read_center_dir = root / "outputs/v18/read_center"
    candidates_csv = candidate_dir / "V18_13B_CURRENT_RANKED_CANDIDATES.csv"
    audit_csv = candidate_dir / "V18_13B_CURRENT_RANKED_CANDIDATES_INPUT_AUDIT.csv"
    read_center_md = read_center_dir / "V18_13B_CURRENT_RANKED_CANDIDATE_READ_CENTER.md"
    read_first_txt = read_center_dir / "V18_13B_READ_FIRST.txt"
    summary_csv = read_center_dir / "V18_13B_CURRENT_RANKED_CANDIDATE_SUMMARY.csv"

    audit: List[Dict[str, object]] = []
    tickers = read_tickers(universe_path)
    evidence = {ticker: CandidateEvidence(ticker=ticker) for ticker in tickers}
    universe = set(tickers)
    audit.append(load_yaml_audit(root, universe_path, len(tickers)))
    load_price_inputs(root, universe, evidence, audit)
    scan_result = scan_sources(root, universe, evidence, audit)
    rows, status, rank_source_status, scored_count, unscored_count = build_rows(evidence, scan_result)
    scan_result.status = status
    scan_result.rank_source_status = rank_source_status
    top5 = ",".join(str(r["ticker"]) for r in rows[:5])

    summary_rows = [
        {"metric": "STATUS", "value": status},
        {"metric": "RANK_SOURCE_STATUS", "value": rank_source_status},
        {"metric": "SECOND_STAGE_COUNT", "value": len(tickers)},
        {"metric": "SCORED_TICKER_COUNT", "value": scored_count},
        {"metric": "UNSCORED_TICKER_COUNT", "value": unscored_count},
        {"metric": "TOP_5_TICKERS", "value": top5},
        {"metric": "PRIMARY_SCORE_SOURCE_FILES", "value": ";".join(scan_result.primary_score_source_files) or "NONE"},
        {"metric": "AUDIT_ONLY_SOURCE_FILES", "value": ";".join(scan_result.audit_only_source_files) or "NONE"},
        {"metric": "RANKING_SOURCE_POLICY", "value": scan_result.ranking_source_policy},
        {"metric": "OFFICIAL_DECISION_IMPACT", "value": OFFICIAL_DECISION_IMPACT},
        {"metric": "AUTO_TRADE", "value": AUTO_TRADE},
        {"metric": "AUTO_SELL", "value": AUTO_SELL},
        {"metric": "READ_ONLY", "value": READ_ONLY},
        {"metric": "READ_FIRST", "value": rel_path(root, read_first_txt)},
        {"metric": "READ_CENTER", "value": rel_path(root, read_center_md)},
        {"metric": "CSV", "value": rel_path(root, candidates_csv)},
    ]

    write_csv(candidates_csv, rows, CANDIDATE_FIELDS)
    write_csv(audit_csv, audit, AUDIT_FIELDS)
    write_text(read_center_md, make_read_center(rows, audit, scan_result, len(tickers), scored_count, unscored_count))
    write_text(read_first_txt, make_read_first(status, rank_source_status, len(tickers), top5, read_center_md, candidates_csv, root))
    write_csv(summary_csv, summary_rows, ["metric", "value"])

    output_paths = [candidates_csv, audit_csv, read_center_md, read_first_txt, summary_csv]
    hits = dangerous_token_hits(output_paths)
    if hits:
        failure_text = "\n".join(
            [
                f"STATUS: {STATUS_FAIL_DANGEROUS}",
                f"RANK_SOURCE_STATUS: {rank_source_status}",
                f"SECOND_STAGE_COUNT: {len(tickers)}",
                f"OFFICIAL_DECISION_IMPACT: {OFFICIAL_DECISION_IMPACT}",
                f"AUTO_TRADE: {AUTO_TRADE}",
                f"AUTO_SELL: {AUTO_SELL}",
                f"READ_ONLY: {READ_ONLY}",
                "ERRORS:",
                *hits,
                "",
            ]
        )
        write_text(read_first_txt, failure_text)
        raise RuntimeError(STATUS_FAIL_DANGEROUS)

    result = {str(r["metric"]): str(r["value"]) for r in summary_rows}
    for key in ("STATUS", "RANK_SOURCE_STATUS", "SECOND_STAGE_COUNT", "SCORED_TICKER_COUNT", "UNSCORED_TICKER_COUNT", "TOP_5_TICKERS", "READ_FIRST", "READ_CENTER", "CSV"):
        print(f"{key}: {result.get(key, '')}")
    return result


def write_error_outputs(root: Path, message: str) -> None:
    read_center_dir = root / "outputs/v18/read_center"
    ensure_dir(read_center_dir)
    text = "\n".join(
        [
            f"STATUS: ERROR_V18_13B_RANKED_CANDIDATE_READ_CENTER_FAILED",
            f"RANK_SOURCE_STATUS: ERROR",
            f"SECOND_STAGE_COUNT: 0",
            f"OFFICIAL_DECISION_IMPACT: {OFFICIAL_DECISION_IMPACT}",
            f"AUTO_TRADE: {AUTO_TRADE}",
            f"AUTO_SELL: {AUTO_SELL}",
            f"READ_ONLY: {READ_ONLY}",
            f"ERROR: {message}",
            "",
        ]
    )
    write_text(read_center_dir / "V18_13B_READ_FIRST.txt", text)
    write_text(read_center_dir / "V18_13B_CURRENT_RANKED_CANDIDATE_READ_CENTER.md", text)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(ROOT_DEFAULT))
    args = parser.parse_args()
    root = Path(args.root)
    try:
        run(root)
        return 0
    except Exception as exc:
        write_error_outputs(root, f"{exc}\n{traceback.format_exc(limit=5)}")
        print(f"STATUS: ERROR_V18_13B_RANKED_CANDIDATE_READ_CENTER_FAILED")
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
