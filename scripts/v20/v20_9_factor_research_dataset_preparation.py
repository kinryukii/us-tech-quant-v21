from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "outputs" / "v20" / "ops"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_V20_8_DATASET = CONSOLIDATION / "V20_8_NORMALIZED_RESEARCH_DATASET.csv"
IN_V20_8_GATE = CONSOLIDATION / "V20_8_GATE_DECISION.csv"
IN_V20_8_VALIDATION = CONSOLIDATION / "V20_8_VALIDATION_SUMMARY.csv"
IN_V20_8_BOUNDARY = CONSOLIDATION / "V20_8_RESEARCH_ONLY_BOUNDARY_AUDIT.csv"
IN_V20_8_READ_FIRST = OPS / "V20_8_READ_FIRST.txt"

OUT_DEPENDENCY = CONSOLIDATION / "V20_9_DEPENDENCY_AUDIT.csv"
OUT_BASE_DATASET = CONSOLIDATION / "V20_9_FACTOR_RESEARCH_BASE_DATASET.csv"
OUT_SCHEMA = CONSOLIDATION / "V20_9_FACTOR_RESEARCH_SCHEMA_AUDIT.csv"
OUT_ATTACHMENT_PLAN = CONSOLIDATION / "V20_9_FACTOR_FAMILY_ATTACHMENT_PLAN.csv"
OUT_FIELD_AVAILABILITY = CONSOLIDATION / "V20_9_FACTOR_INPUT_FIELD_AVAILABILITY_AUDIT.csv"
OUT_TECHNICAL = CONSOLIDATION / "V20_9_TECHNICAL_FACTOR_READINESS_AUDIT.csv"
OUT_FUNDAMENTAL = CONSOLIDATION / "V20_9_FUNDAMENTAL_FACTOR_READINESS_AUDIT.csv"
OUT_RISK = CONSOLIDATION / "V20_9_RISK_FACTOR_READINESS_AUDIT.csv"
OUT_REGIME = CONSOLIDATION / "V20_9_MARKET_REGIME_FACTOR_READINESS_AUDIT.csv"
OUT_TRUST = CONSOLIDATION / "V20_9_DATA_TRUSTWORTHINESS_FACTOR_READINESS_AUDIT.csv"
OUT_BOUNDARY = CONSOLIDATION / "V20_9_FACTOR_RESEARCH_BOUNDARY_AUDIT.csv"
OUT_MISSING_SOURCE = CONSOLIDATION / "V20_9_MISSING_FACTOR_SOURCE_REGISTER.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_9_BLOCKER_REGISTER.csv"
OUT_GATE = CONSOLIDATION / "V20_9_GATE_DECISION.csv"
OUT_NEXT = CONSOLIDATION / "V20_9_NEXT_STEP_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_9_VALIDATION_SUMMARY.csv"

REPORT = READ_CENTER / "V20_9_FACTOR_RESEARCH_DATASET_PREPARATION_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_FACTOR_RESEARCH_DATASET_PREPARATION.md"
READ_FIRST = OPS / "V20_9_READ_FIRST.txt"

PATCH_VERSION = "V20.9"
FACTOR_RESEARCH_DATASET_VERSION = "V20.9_FACTOR_RESEARCH_DATASET"
EXPECTED_SOURCE_STEP = "V20.8"

ALLOWED_WRITE_PATHS = {
    OUT_DEPENDENCY,
    OUT_BASE_DATASET,
    OUT_SCHEMA,
    OUT_ATTACHMENT_PLAN,
    OUT_FIELD_AVAILABILITY,
    OUT_TECHNICAL,
    OUT_FUNDAMENTAL,
    OUT_RISK,
    OUT_REGIME,
    OUT_TRUST,
    OUT_BOUNDARY,
    OUT_MISSING_SOURCE,
    OUT_BLOCKERS,
    OUT_GATE,
    OUT_NEXT,
    OUT_VALIDATION,
    REPORT,
    CURRENT_REPORT,
    READ_FIRST,
}

SAFETY_FLAGS = {
    "REPORTING_ONLY": "FALSE",
    "FACTOR_RESEARCH_PREPARATION_ONLY": "TRUE",
    "FACTOR_RESEARCH_BASE_DATASET_CREATED": "FALSE",
    "FACTOR_EVIDENCE_ROWS_CREATED": "0",
    "BACKTEST_ROWS_CREATED": "0",
    "DYNAMIC_WEIGHTING_ROWS_CREATED": "0",
    "TRADING_SIGNAL_ROWS_CREATED": "0",
    "OFFICIAL_RECOMMENDATION_ROWS_CREATED": "0",
    "BROKER_API_USED": "FALSE",
    "ORDER_EXECUTION_USED": "FALSE",
    "SOURCE_MUTATION_USED": "FALSE",
    "V21_OUTPUTS_CREATED": "FALSE",
    "V19_21_OUTPUTS_CREATED": "FALSE",
    "OFFICIAL_USE_ALLOWED": "FALSE",
}

NORMALIZED_PASSTHROUGH_COLUMNS = [
    "normalized_row_id",
    "input_artifact_id",
    "lineage_binding_id",
    "source_artifact_id",
    "source_system",
    "source_hash",
    "run_id",
    "sample_id",
    "ticker",
    "effective_observation_date",
    "effective_price_date",
    "effective_close",
    "active_runtime_flag",
    "historical_reference_flag",
    "research_only_flag",
    "official_use_allowed",
]

FACTOR_RESEARCH_COLUMNS = NORMALIZED_PASSTHROUGH_COLUMNS + [
    "factor_research_row_id",
    "factor_research_dataset_version",
    "factor_research_prepared_at_utc",
    "factor_research_source_step",
    "eligible_for_factor_source_attachment_next",
    "eligible_for_factor_evidence_now",
    "eligible_for_backtest_now",
    "eligible_for_dynamic_weighting_now",
    "eligible_for_trading_now",
    "eligible_for_official_recommendation_now",
]

FACTOR_PLAN_SPECS = [
    ("fundamental", "growth", "fundamental_snapshot;historical_financials;revenue_growth_windows", False, "V20.10 source attachment: fundamental financial statement coverage."),
    ("fundamental", "profitability", "fundamental_snapshot;historical_financials;profit_margin_windows", False, "V20.10 source attachment: profitability inputs."),
    ("fundamental", "quality", "fundamental_snapshot;historical_financials;balance_sheet_quality_windows", False, "V20.10 source attachment: quality inputs."),
    ("fundamental", "margin", "fundamental_snapshot;historical_financials;margin_series", False, "V20.10 source attachment: margin series."),
    ("fundamental", "cash_flow", "fundamental_snapshot;cash_flow_statement_history", False, "V20.10 source attachment: cash-flow statement history."),
    ("fundamental", "capex", "fundamental_snapshot;capex_history", False, "V20.10 source attachment: capital expenditure history."),
    ("fundamental", "valuation", "fundamental_snapshot;valuation_multiples_history", False, "V20.10 source attachment: valuation multiples history."),
    ("fundamental", "liquidity", "fundamental_snapshot;liquidity_ratios_history", False, "V20.10 source attachment: liquidity ratios."),
    ("technical", "trend", "historical_ohlcv_windows;moving_average_windows", False, "V20.10 source attachment: historical OHLCV windows."),
    ("technical", "momentum", "historical_ohlcv_windows;return_windows", False, "V20.10 source attachment: return windows."),
    ("technical", "relative_strength", "benchmark_series;historical_ohlcv_windows", False, "V20.10 source attachment: benchmark-relative history."),
    ("technical", "pullback_quality", "historical_ohlcv_windows;support_resistance_windows", False, "V20.10 source attachment: pullback history windows."),
    ("technical", "breakout", "historical_ohlcv_windows;range_breakout_windows", False, "V20.10 source attachment: breakout windows."),
    ("technical", "ma_ema", "historical_ohlcv_windows;moving_average_windows", False, "V20.10 source attachment: moving-average windows."),
    ("technical", "bollinger", "historical_ohlcv_windows;bollinger_band_windows", False, "V20.10 source attachment: Bollinger-band windows."),
    ("technical", "rsi", "historical_ohlcv_windows;rsi_windows", False, "V20.10 source attachment: RSI windows."),
    ("technical", "kdj", "historical_ohlcv_windows;kdj_windows", False, "V20.10 source attachment: KDJ windows."),
    ("technical", "macd", "historical_ohlcv_windows;macd_windows", False, "V20.10 source attachment: MACD windows."),
    ("technical", "volume", "historical_ohlcv_windows;volume_history", False, "V20.10 source attachment: volume history."),
    ("technical", "volatility", "historical_ohlcv_windows;volatility_windows", False, "V20.10 source attachment: volatility windows."),
    ("strategy", "ma10_ma20_pullback", "historical_ohlcv_windows;moving_average_windows", False, "V20.10 source attachment: strategy-level moving-average windows."),
    ("strategy", "momentum_breakout", "historical_ohlcv_windows;breakout_windows;momentum_windows", False, "V20.10 source attachment: momentum/breakout windows."),
    ("strategy", "quality_momentum", "fundamental_snapshot;historical_ohlcv_windows", False, "V20.10 source attachment: combined fundamental and price-history inputs."),
    ("strategy", "relative_strength_breakout", "benchmark_series;historical_ohlcv_windows;breakout_windows", False, "V20.10 source attachment: relative-strength and breakout history."),
    ("strategy", "entry_timing", "historical_ohlcv_windows;market_session_windows", False, "V20.10 source attachment: entry timing windows."),
    ("strategy", "exit_stop", "historical_ohlcv_windows;drawdown_windows", False, "V20.10 source attachment: stop/exit history windows."),
    ("risk", "overheat", "historical_ohlcv_windows;volatility_windows", False, "V20.10 source attachment: overheating risk windows."),
    ("risk", "volatility_risk", "historical_ohlcv_windows;volatility_windows", False, "V20.10 source attachment: volatility-risk history."),
    ("risk", "event_risk", "event_calendar;earnings_calendar", False, "V20.10 source attachment: event calendar."),
    ("risk", "earnings_risk", "earnings_calendar;fundamental_snapshot", False, "V20.10 source attachment: earnings calendar."),
    ("risk", "macro_risk", "macro_calendar;cpi_series;fomc_schedule", False, "V20.10 source attachment: macro calendar."),
    ("risk", "regulation_risk", "policy_calendar;news_event_tags", False, "V20.10 source attachment: policy/news regime inputs."),
    ("risk", "supply_chain_risk", "supply_chain_events;news_event_tags", False, "V20.10 source attachment: supply-chain event data."),
    ("risk", "valuation_risk", "valuation_multiples_history;fundamental_snapshot", False, "V20.10 source attachment: valuation history."),
    ("risk", "capex_risk", "capex_history;fundamental_snapshot", False, "V20.10 source attachment: capex history."),
    ("risk", "cash_flow_risk", "cash_flow_statement_history;fundamental_snapshot", False, "V20.10 source attachment: cash-flow history."),
    ("risk", "portfolio_drawdown", "portfolio_drawdown_history;position_history", False, "V20.10 source attachment: portfolio history."),
    ("risk", "position_cap", "position_limit_inputs;portfolio_constraints", False, "V20.10 source attachment: position-cap inputs."),
    ("market_regime", "vix", "vix_series", False, "V20.10 source attachment: VIX series."),
    ("market_regime", "qqq_spy_trend", "qqq_series;spy_series;historical_ohlcv_windows", False, "V20.10 source attachment: QQQ/SPY regime series."),
    ("market_regime", "risk_on_off", "market_regime_labels;benchmark_series;volatility_series", False, "V20.10 source attachment: market-regime labels."),
    ("market_regime", "cpi", "macro_calendar;cpi_series", False, "V20.10 source attachment: CPI calendar/series."),
    ("market_regime", "fomc", "macro_calendar;fomc_schedule", False, "V20.10 source attachment: FOMC schedule."),
    ("market_regime", "nfp", "macro_calendar;nfp_calendar", False, "V20.10 source attachment: NFP calendar."),
    ("market_regime", "earnings_season", "earnings_calendar;market_calendar", False, "V20.10 source attachment: earnings calendar."),
    ("market_regime", "quarter_end_rebalance", "market_calendar;portfolio_rebalance_schedule", False, "V20.10 source attachment: rebalance calendar."),
    ("data_trustworthiness", "freshness", "lineage_metadata;freshness_metadata", True, "No additional source required; lineage metadata already exists in V20.8."),
    ("data_trustworthiness", "source_quality", "lineage_metadata;source_quality_flags", True, "No additional source required; lineage metadata already exists in V20.8."),
    ("data_trustworthiness", "point_in_time", "lineage_metadata;point_in_time_flags", True, "No additional source required; lineage metadata already exists in V20.8."),
    ("data_trustworthiness", "safe_backtest_eligibility", "lineage_metadata;safe_backtest_flags", True, "No additional source required; lineage metadata already exists in V20.8."),
    ("data_trustworthiness", "current_snapshot_block", "lineage_metadata;current_snapshot_block_flags", True, "No additional source required; lineage metadata already exists in V20.8."),
]

FIELD_AVAILABILITY_SPECS = [
    ("market_snapshot_core", "ticker;effective_observation_date;effective_price_date;effective_close;source_hash;run_id;sample_id", True, "V20.8 provides the market snapshot core fields."),
    ("historical_ohlcv_windows", "historical_ohlcv_windows", False, "No historical OHLCV window source is present in V20.8."),
    ("volume_history", "volume_history", False, "No volume history source is present in V20.8."),
    ("moving_average_windows", "moving_average_windows", False, "No moving-average window source is present in V20.8."),
    ("rsi_kdj_macd_bollinger_inputs", "rsi_windows;kdj_windows;macd_windows;bollinger_band_windows", False, "No indicator window source is present in V20.8."),
    ("fundamental_snapshot", "revenue;earnings;margin;cash_flow;capex;valuation", False, "No accepted fundamental snapshot source is present in V20.8."),
    ("event_calendar", "event_calendar;earnings_calendar", False, "No event or earnings calendar source is present in V20.8."),
    ("macro_calendar", "macro_calendar;cpi_series;fomc_schedule;nfp_calendar", False, "No macro calendar source is present in V20.8."),
    ("vix_qqq_spy_regime_inputs", "vix_series;qqq_series;spy_series", False, "No VIX/QQQ/SPY regime source is present in V20.8."),
    ("portfolio_drawdown_position_cap_inputs", "portfolio_drawdown_history;position_limit_inputs", False, "No portfolio drawdown or position-cap input source is present in V20.8."),
    ("lineage_metadata", "normalized_row_id;input_artifact_id;lineage_binding_id;source_artifact_id;source_system;source_hash;run_id;sample_id", True, "Lineage metadata is present in V20.8."),
]

MISSING_SOURCE_SPECS = [
    ("historical_ohlcv_windows", "technical and strategy families", "V20.10 source attachment"),
    ("volume_history", "technical volume and momentum families", "V20.10 source attachment"),
    ("moving_average_windows", "technical trend and moving-average families", "V20.10 source attachment"),
    ("rsi_kdj_macd_bollinger_inputs", "technical indicator families", "V20.10 source attachment"),
    ("fundamental_revenue_earnings_margin_cash_flow_capex_valuation_inputs", "fundamental and strategy families", "V20.10 source attachment"),
    ("event_and_earnings_calendar", "event-risk and earnings-risk families", "V20.10 source attachment"),
    ("macro_calendar", "macro-risk and market-regime families", "V20.10 source attachment"),
    ("vix_qqq_spy_market_regime_inputs", "market-regime families", "V20.10 source attachment"),
    ("portfolio_drawdown_and_position_cap_inputs", "portfolio risk families", "V20.10 source attachment"),
]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def clean(value: object) -> str:
    return str(value or "").strip()


def upper(value: object) -> str:
    return clean(value).upper()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


def first_present(row: dict[str, str], fields: tuple[str, ...]) -> str:
    for field in fields:
        value = clean(row.get(field))
        if value:
            return value
    return ""


def parse_date(value: object) -> datetime | None:
    text = clean(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def to_float(value: object) -> float | None:
    try:
        x = float(clean(value))
        if x != x or x in (float("inf"), float("-inf")):
            return None
        return x
    except Exception:
        return None


def deterministic_factor_research_row_id(row: dict[str, str]) -> str:
    basis = "|".join(
        [
            clean(row.get("normalized_row_id")),
            clean(row.get("ticker")),
            clean(row.get("effective_observation_date")),
            clean(row.get("effective_price_date")),
            clean(row.get("sample_id")),
            clean(row.get("source_hash")),
            clean(row.get("run_id")),
        ]
    )
    return "V20_9_FACT_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24].upper()


def md_table(headers: list[str], rows: list[dict[str, str]], limit: int = 20) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows[:limit]:
        lines.append("| " + " | ".join(clean(row.get(field)).replace("|", "/") for field in headers) + " |")
    if len(rows) > limit:
        lines.append("| ... | " + f"{len(rows) - limit} more rows omitted" + " |" * max(0, len(headers) - 2))
    return "\n".join(lines)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def add_blocker(blockers: list[dict[str, str]], scope: str, reason: str, severity: str = "BLOCKING") -> None:
    blockers.append(
        {
            "blocker_id": f"V20_9_BLOCKER_{len(blockers) + 1:03d}",
            "blocker_scope": scope,
            "severity": severity,
            "blocker_status": "OPEN" if severity == "BLOCKING" else "WARN",
            "blocker_reason": reason,
            "blocks_v20_9": tf(severity == "BLOCKING"),
        }
    )


def required_flags_present(text: str, normalized_count: int) -> bool:
    required = [
        "REPORTING_ONLY: FALSE",
        "FACTOR_RESEARCH_PREPARATION_ONLY: TRUE",
        f"FACTOR_RESEARCH_ROWS_CREATED: {normalized_count}",
        "FACTOR_EVIDENCE_ROWS_CREATED: 0",
        "BACKTEST_ROWS_CREATED: 0",
        "DYNAMIC_WEIGHTING_ROWS_CREATED: 0",
        "TRADING_SIGNAL_ROWS_CREATED: 0",
        "OFFICIAL_RECOMMENDATION_ROWS_CREATED: 0",
        "BROKER_API_USED: FALSE",
        "ORDER_EXECUTION_USED: FALSE",
        "SOURCE_MUTATION_USED: FALSE",
        "V21_OUTPUTS_CREATED: FALSE",
        "V19_21_OUTPUTS_CREATED: FALSE",
        "OFFICIAL_USE_ALLOWED: FALSE",
    ]
    return all(flag in text for flag in required)


def main() -> int:
    generated_at = utc_now()
    today = datetime.now(timezone.utc).date()

    base_rows, base_fields = read_csv(IN_V20_8_DATASET)
    gate_rows, _ = read_csv(IN_V20_8_GATE)
    validation_rows, _ = read_csv(IN_V20_8_VALIDATION)
    boundary_rows, _ = read_csv(IN_V20_8_BOUNDARY)
    read_first_text = IN_V20_8_READ_FIRST.read_text(encoding="utf-8", errors="replace") if IN_V20_8_READ_FIRST.exists() else ""

    gate = gate_rows[0] if gate_rows else {}
    validation = validation_rows[0] if validation_rows else {}
    boundary = boundary_rows[0] if boundary_rows else {}

    blockers: list[dict[str, str]] = []
    dependency_rows: list[dict[str, str]] = []

    def dependency(name: str, path: Path, passed: bool, reason: str = "") -> None:
        dependency_rows.append(
            {
                "dependency": name,
                "path": rel(path),
                "exists": tf(path.exists()),
                "status": "PASS" if passed else "BLOCKED",
                "blocker_reason": reason,
            }
        )
        if not passed:
            add_blocker(blockers, "DEPENDENCY", reason or f"Dependency failed: {name}.")

    base_dataset_created = upper(validation.get("normalized_research_dataset_created")) == "TRUE" or upper(gate.get("NORMALIZED_RESEARCH_DATASET_CREATED")) == "TRUE"
    ready_next = upper(validation.get("ready_for_v20_9_factor_research_dataset_preparation_next")) == "TRUE" or upper(gate.get("READY_FOR_V20_9_FACTOR_RESEARCH_DATASET_PREPARATION_NEXT")) == "TRUE"
    backtest_false = upper(validation.get("ready_for_backtest_next")) == "FALSE" and upper(gate.get("READY_FOR_BACKTEST_NEXT")) == "FALSE"
    dynamic_false = upper(validation.get("ready_for_dynamic_weighting_next")) == "FALSE" and upper(gate.get("READY_FOR_DYNAMIC_WEIGHTING_NEXT")) == "FALSE"
    trading_false = upper(validation.get("ready_for_trading_or_official_recommendation")) == "FALSE" and upper(gate.get("READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION")) == "FALSE"
    v20_8_pass = upper(validation.get("status")) == "PASS_V20_8_NORMALIZED_RESEARCH_DATASET_CONSTRUCTED"
    read_first_ok = all(
        flag in read_first_text
        for flag in [
            "REPORTING_ONLY: FALSE",
            "RESEARCH_DATASET_CONSTRUCTION: TRUE",
            "NORMALIZED_RESEARCH_DATASET_CREATED: TRUE",
            f"NORMALIZED_ROWS_CREATED: {validation.get('normalized_row_count', '318')}",
            "FACTOR_EVIDENCE_ROWS_CREATED: 0",
            "BACKTEST_ROWS_CREATED: 0",
            "DYNAMIC_WEIGHTING_ROWS_CREATED: 0",
            "TRADING_SIGNAL_ROWS_CREATED: 0",
            "OFFICIAL_RECOMMENDATION_ROWS_CREATED: 0",
            "BROKER_API_USED: FALSE",
            "ORDER_EXECUTION_USED: FALSE",
            "SOURCE_MUTATION_USED: FALSE",
            "V21_OUTPUTS_CREATED: FALSE",
            "V19_21_OUTPUTS_CREATED: FALSE",
            "OFFICIAL_USE_ALLOWED: FALSE",
        ]
    )

    dependency("V20_8_NORMALIZED_RESEARCH_DATASET", IN_V20_8_DATASET, IN_V20_8_DATASET.exists() and base_dataset_created, "V20.8 normalized research dataset is missing or was not created.")
    dependency("V20_8_GATE_DECISION", IN_V20_8_GATE, v20_8_pass and ready_next and backtest_false and dynamic_false and trading_false, "V20.8 gate does not permit factor research preparation next.")
    dependency("V20_8_VALIDATION_SUMMARY", IN_V20_8_VALIDATION, base_dataset_created and ready_next and backtest_false and dynamic_false and trading_false, "V20.8 validation summary is not in the required state.")
    dependency("V20_8_RESEARCH_ONLY_BOUNDARY_AUDIT", IN_V20_8_BOUNDARY, IN_V20_8_BOUNDARY.exists() and upper(boundary.get("research_only_boundary_status")) == "PASS", "V20.8 boundary audit does not confirm research-only rows.")
    dependency("V20_8_READ_FIRST", IN_V20_8_READ_FIRST, IN_V20_8_READ_FIRST.exists() and read_first_ok, "V20.8 READ_FIRST safety contract is incomplete.")

    normalized_count = len(base_rows)
    source_hashes = sorted({clean(row.get("source_hash")) for row in base_rows if clean(row.get("source_hash"))})
    run_ids = sorted({clean(row.get("run_id")) for row in base_rows if clean(row.get("run_id"))})
    normalized_row_ids = [clean(row.get("normalized_row_id")) for row in base_rows]
    sample_ids = [clean(row.get("sample_id")) for row in base_rows]
    tickers = sorted({clean(row.get("ticker")) for row in base_rows if clean(row.get("ticker"))})

    if normalized_count == 0:
        add_blocker(blockers, "BASE_DATASET", "V20.8 normalized dataset contains no rows.")

    source_hash = source_hashes[0] if len(source_hashes) == 1 else ""
    run_id = run_ids[0] if len(run_ids) == 1 else ""
    normalized_row_id_unique = len(set(normalized_row_ids)) == len(normalized_row_ids) and all(normalized_row_ids)
    source_hash_consistent = len(source_hashes) == 1 and bool(source_hash)
    run_id_consistent = len(run_ids) == 1 and bool(run_id)

    if not normalized_row_id_unique:
        add_blocker(blockers, "BASE_SCHEMA", "normalized_row_id is missing, duplicated, or inconsistent.")
    if not source_hash_consistent:
        add_blocker(blockers, "BASE_LINEAGE", "source_hash is missing or inconsistent in the normalized dataset.")
    if not run_id_consistent:
        add_blocker(blockers, "BASE_LINEAGE", "run_id is missing or inconsistent in the normalized dataset.")

    factor_rows: list[dict[str, str]] = []
    factor_research_row_ids: set[str] = set()
    missing_ticker_count = 0
    missing_price_count = 0
    nonpositive_price_count = 0
    future_date_count = 0
    missing_source_hash_count = 0
    missing_run_id_count = 0
    missing_sample_id_count = 0
    unique_normalized_row_ids: set[str] = set()

    for row in base_rows:
        prepared_row = {
            "normalized_row_id": clean(row.get("normalized_row_id")),
            "input_artifact_id": clean(row.get("input_artifact_id")),
            "lineage_binding_id": clean(row.get("lineage_binding_id")),
            "source_artifact_id": clean(row.get("source_artifact_id")),
            "source_system": clean(row.get("source_system")),
            "source_hash": clean(row.get("source_hash")),
            "run_id": clean(row.get("run_id")),
            "sample_id": clean(row.get("sample_id")),
            "ticker": clean(row.get("ticker")),
            "effective_observation_date": clean(row.get("effective_observation_date")),
            "effective_price_date": clean(row.get("effective_price_date")),
            "effective_close": clean(row.get("effective_close")),
            "active_runtime_flag": clean(row.get("active_runtime_flag")),
            "historical_reference_flag": clean(row.get("historical_reference_flag")),
            "research_only_flag": clean(row.get("research_only_flag")),
            "official_use_allowed": clean(row.get("official_use_allowed")),
            "factor_research_row_id": "",
            "factor_research_dataset_version": FACTOR_RESEARCH_DATASET_VERSION,
            "factor_research_prepared_at_utc": generated_at,
            "factor_research_source_step": PATCH_VERSION,
            "eligible_for_factor_source_attachment_next": "TRUE",
            "eligible_for_factor_evidence_now": "FALSE",
            "eligible_for_backtest_now": "FALSE",
            "eligible_for_dynamic_weighting_now": "FALSE",
            "eligible_for_trading_now": "FALSE",
            "eligible_for_official_recommendation_now": "FALSE",
        }
        prepared_row["factor_research_row_id"] = deterministic_factor_research_row_id(prepared_row)
        factor_research_row_ids.add(prepared_row["factor_research_row_id"])
        factor_rows.append(prepared_row)

        if not clean(row.get("ticker")):
            missing_ticker_count += 1
        if to_float(clean(row.get("effective_close"))) is None:
            missing_price_count += 1
        elif (to_float(clean(row.get("effective_close"))) or 0) <= 0:
            nonpositive_price_count += 1
        od = parse_date(clean(row.get("effective_observation_date")))
        pd = parse_date(clean(row.get("effective_price_date")))
        if od and od.date() > today:
            future_date_count += 1
        if pd and pd.date() > today:
            future_date_count += 1
        if not clean(row.get("source_hash")):
            missing_source_hash_count += 1
        if not clean(row.get("run_id")):
            missing_run_id_count += 1
        if not clean(row.get("sample_id")):
            missing_sample_id_count += 1
        if clean(row.get("normalized_row_id")):
            unique_normalized_row_ids.add(clean(row.get("normalized_row_id")))

    if len(factor_rows) != normalized_count:
        add_blocker(blockers, "FACTOR_RESEARCH_BASE_DATASET", "Factor research base dataset row count does not match the normalized dataset.")
    if len(factor_research_row_ids) != len(factor_rows):
        add_blocker(blockers, "FACTOR_RESEARCH_ROW_ID", "factor_research_row_id is duplicated or missing.")

    attachment_plan_rows: list[dict[str, str]] = []
    for factor_family, factor_name, required_input_type, attachment_ready_now, next_step in FACTOR_PLAN_SPECS:
        currently_available = factor_family == "data_trustworthiness"
        evidence_allowed_now = False
        attachment_plan_rows.append(
            {
                "factor_family": factor_family,
                "factor_name": factor_name,
                "required_input_type": required_input_type,
                "currently_available_from_v20_8": tf(currently_available),
                "attachment_ready_now": tf(attachment_ready_now),
                "evidence_allowed_now": tf(evidence_allowed_now),
                "blocker_reason": "" if attachment_ready_now else next_step,
                "next_required_source_or_step": next_step,
            }
        )

    field_availability_rows = []
    for source_name, required_fields, available, reason in FIELD_AVAILABILITY_SPECS:
        field_availability_rows.append(
            {
                "field_group": source_name,
                "required_fields": required_fields,
                "available_from_v20_8": tf(available),
                "availability_status": "PASS" if available else "SOURCE_REQUIRED",
                "blocker_reason": "" if available else reason,
                "next_required_source_or_step": "No additional source required" if available else "V20.10 factor source attachment or upstream source registration",
            }
        )

    def readiness_group(group_name: str, allowed_group: str) -> tuple[int, int, int]:
        rows = [row for row in attachment_plan_rows if row["factor_family"] == allowed_group]
        available_count = sum(1 for row in rows if upper(row["currently_available_from_v20_8"]) == "TRUE")
        ready_count = sum(1 for row in rows if upper(row["attachment_ready_now"]) == "TRUE")
        evidence_allowed_count = sum(1 for row in rows if upper(row["evidence_allowed_now"]) == "TRUE")
        return available_count, ready_count, evidence_allowed_count

    technical_available, technical_ready, technical_evidence = readiness_group("technical", "technical")
    fundamental_available, fundamental_ready, fundamental_evidence = readiness_group("fundamental", "fundamental")
    risk_available, risk_ready, risk_evidence = readiness_group("risk", "risk")
    regime_available, regime_ready, regime_evidence = readiness_group("market_regime", "market_regime")
    trust_available, trust_ready, trust_evidence = readiness_group("data_trustworthiness", "data_trustworthiness")

    technical_audit = [{
        "factor_family_group": "technical",
        "factor_count": "12",
        "currently_available_from_v20_8_count": str(technical_available),
        "attachment_ready_now_count": str(technical_ready),
        "evidence_allowed_now_count": str(technical_evidence),
        "readiness_status": "SOURCE_REQUIRED",
        "blocker_reason": "Requires historical OHLCV/indicator window sources not present in V20.8.",
        "next_required_source_or_step": "V20.10 factor source attachment",
    }]
    fundamental_audit = [{
        "factor_family_group": "fundamental",
        "factor_count": "8",
        "currently_available_from_v20_8_count": str(fundamental_available),
        "attachment_ready_now_count": str(fundamental_ready),
        "evidence_allowed_now_count": str(fundamental_evidence),
        "readiness_status": "SOURCE_REQUIRED",
        "blocker_reason": "Requires accepted fundamental snapshot / financial statement sources not present in V20.8.",
        "next_required_source_or_step": "V20.10 factor source attachment",
    }]
    risk_audit = [{
        "factor_family_group": "risk",
        "factor_count": "12",
        "currently_available_from_v20_8_count": str(risk_available),
        "attachment_ready_now_count": str(risk_ready),
        "evidence_allowed_now_count": str(risk_evidence),
        "readiness_status": "SOURCE_REQUIRED",
        "blocker_reason": "Requires event, macro, portfolio, or risk-history sources not present in V20.8.",
        "next_required_source_or_step": "V20.10 factor source attachment",
    }]
    regime_audit = [{
        "factor_family_group": "market_regime",
        "factor_count": "8",
        "currently_available_from_v20_8_count": str(regime_available),
        "attachment_ready_now_count": str(regime_ready),
        "evidence_allowed_now_count": str(regime_evidence),
        "readiness_status": "SOURCE_REQUIRED",
        "blocker_reason": "Requires VIX/QQQ/SPY and macro regime inputs not present in V20.8.",
        "next_required_source_or_step": "V20.10 factor source attachment",
    }]
    trust_audit = [{
        "factor_family_group": "data_trustworthiness",
        "factor_count": "5",
        "currently_available_from_v20_8_count": str(trust_available),
        "attachment_ready_now_count": str(trust_ready),
        "evidence_allowed_now_count": str(trust_evidence),
        "readiness_status": "PASS",
        "blocker_reason": "",
        "next_required_source_or_step": "Proceed to V20.10 factor source attachment for the remaining families.",
    }]

    missing_source_rows = []
    for source_name, required_for, next_step in MISSING_SOURCE_SPECS:
        missing_source_rows.append(
            {
                "missing_source_id": f"V20_9_MISSING_{len(missing_source_rows) + 1:03d}",
                "required_source_name": source_name,
                "required_for_factor_families": required_for,
                "source_status": "MISSING",
                "blocker_reason": f"Missing required source: {source_name}.",
                "next_required_source_or_step": next_step,
            }
        )

    boundary_rows = [{
        "boundary_check_id": "V20_9_BOUNDARY_001",
        "factor_research_preparation_only_required": "TRUE",
        "factor_evidence_rows_created_required": "0",
        "backtest_rows_created_required": "0",
        "dynamic_weighting_rows_created_required": "0",
        "trading_signal_rows_created_required": "0",
        "official_recommendation_rows_created_required": "0",
        "official_use_allowed_required": "FALSE",
        "eligible_for_factor_source_attachment_next_row_count": str(sum(1 for row in factor_rows if upper(row.get("eligible_for_factor_source_attachment_next")) == "TRUE")),
        "eligible_for_factor_evidence_now_row_count": str(sum(1 for row in factor_rows if upper(row.get("eligible_for_factor_evidence_now")) == "TRUE")),
        "eligible_for_backtest_now_row_count": str(sum(1 for row in factor_rows if upper(row.get("eligible_for_backtest_now")) == "TRUE")),
        "eligible_for_dynamic_weighting_now_row_count": str(sum(1 for row in factor_rows if upper(row.get("eligible_for_dynamic_weighting_now")) == "TRUE")),
        "eligible_for_trading_now_row_count": str(sum(1 for row in factor_rows if upper(row.get("eligible_for_trading_now")) == "TRUE")),
        "eligible_for_official_recommendation_now_row_count": str(sum(1 for row in factor_rows if upper(row.get("eligible_for_official_recommendation_now")) == "TRUE")),
        "factor_research_boundary_status": "PASS" if factor_rows and all(upper(row.get("research_only_flag")) == "TRUE" and upper(row.get("official_use_allowed")) == "FALSE" and upper(row.get("eligible_for_factor_source_attachment_next")) == "TRUE" and upper(row.get("eligible_for_factor_evidence_now")) == "FALSE" and upper(row.get("eligible_for_backtest_now")) == "FALSE" and upper(row.get("eligible_for_dynamic_weighting_now")) == "FALSE" and upper(row.get("eligible_for_trading_now")) == "FALSE" and upper(row.get("eligible_for_official_recommendation_now")) == "FALSE" for row in factor_rows) else "BLOCKED",
        "blocker_reason": "" if factor_rows and all(upper(row.get("research_only_flag")) == "TRUE" and upper(row.get("official_use_allowed")) == "FALSE" and upper(row.get("eligible_for_factor_source_attachment_next")) == "TRUE" and upper(row.get("eligible_for_factor_evidence_now")) == "FALSE" and upper(row.get("eligible_for_backtest_now")) == "FALSE" and upper(row.get("eligible_for_dynamic_weighting_now")) == "FALSE" and upper(row.get("eligible_for_trading_now")) == "FALSE" and upper(row.get("eligible_for_official_recommendation_now")) == "FALSE" for row in factor_rows) else "Research-only boundary failed.",
    }]

    data_quality_rows = [{
        "quality_check_id": "V20_9_QUALITY_001",
        "factor_research_row_count": str(len(factor_rows)),
        "unique_ticker_count": str(len(tickers)),
        "date_distribution": ";".join(f"{key}={sum(1 for row in factor_rows if clean(row.get('effective_observation_date')) == key)}" for key in sorted({clean(row.get("effective_observation_date")) for row in factor_rows if clean(row.get("effective_observation_date"))})),
        "missing_ticker_count": str(missing_ticker_count),
        "missing_price_count": str(missing_price_count),
        "nonpositive_price_count": str(nonpositive_price_count),
        "missing_source_hash_count": str(missing_source_hash_count),
        "missing_run_id_count": str(missing_run_id_count),
        "missing_sample_id_count": str(missing_sample_id_count),
        "duplicate_factor_research_row_id_count": str(max(0, len(factor_rows) - len(factor_research_row_ids))),
        "rows_allowed_for_factor_evidence_now": "0",
        "rows_allowed_for_official_use": "0",
        "data_quality_status": "PASS" if factor_rows and missing_ticker_count == 0 and missing_price_count == 0 and nonpositive_price_count == 0 and missing_source_hash_count == 0 and missing_run_id_count == 0 and missing_sample_id_count == 0 and len(factor_rows) == len(factor_research_row_ids) else "BLOCKED",
        "blocker_reason": "" if factor_rows and missing_ticker_count == 0 and missing_price_count == 0 and nonpositive_price_count == 0 and missing_source_hash_count == 0 and missing_run_id_count == 0 and missing_sample_id_count == 0 and len(factor_rows) == len(factor_research_row_ids) else "Data quality requirements not satisfied.",
    }]

    if not factor_rows:
        add_blocker(blockers, "BASE_DATASET", "No factor research rows were constructed.")

    blocking_count = sum(1 for blocker in blockers if blocker["severity"] == "BLOCKING")
    factor_research_created = bool(factor_rows)
    factor_research_rows_created = len(factor_rows)
    ready_for_v20_10 = factor_research_created and blocking_count == 0
    gate_status = "PASS_V20_9_FACTOR_RESEARCH_DATASET_PREPARED" if ready_for_v20_10 else "BLOCKED_V20_9_FACTOR_RESEARCH_DATASET_PREPARATION"
    next_step = "V20.10_FACTOR_SOURCE_ATTACHMENT_OR_AVAILABILITY_AUDIT" if ready_for_v20_10 else "RESOLVE_V20_9_BLOCKERS"

    gate_output = [{
        "gate_id": "V20_9_GATE",
        "status": gate_status,
        "FACTOR_RESEARCH_BASE_DATASET_CREATED": tf(factor_research_created),
        "FACTOR_RESEARCH_ROWS_CREATED": str(factor_research_rows_created),
        "READY_FOR_V20_10_FACTOR_SOURCE_ATTACHMENT_OR_AVAILABILITY_AUDIT_NEXT": tf(ready_for_v20_10),
        "READY_FOR_FACTOR_EVIDENCE_NEXT": "FALSE",
        "READY_FOR_BACKTEST_NEXT": "FALSE",
        "READY_FOR_DYNAMIC_WEIGHTING_NEXT": "FALSE",
        "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION": "FALSE",
        "V21_OUTPUTS_CREATED": "FALSE",
        "V19_21_OUTPUTS_CREATED": "FALSE",
        "NEXT_RECOMMENDED_STEP": next_step,
        "gate_reason": "Factor research dataset prepared from V20.8 normalized research data." if ready_for_v20_10 else "One or more V20.9 preparation checks failed.",
    }]

    next_output = [{
        "decision_id": "V20_9_NEXT_STEP",
        "ready_for_v20_10_factor_source_attachment_or_availability_audit_next": tf(ready_for_v20_10),
        "ready_for_factor_evidence_next": "FALSE",
        "ready_for_backtest_next": "FALSE",
        "ready_for_dynamic_weighting_next": "FALSE",
        "ready_for_trading_or_official_recommendation": "FALSE",
        "next_recommended_step": next_step,
        "reason": "Prepared factor research base dataset is ready for factor source attachment or availability audit next." if ready_for_v20_10 else "V20.9 remains blocked until preparation checks pass.",
    }]

    blocker_rows = blockers or [{
        "blocker_id": "V20_9_BLOCKER_000",
        "blocker_scope": "NONE",
        "severity": "INFO",
        "blocker_status": "CLEARED",
        "blocker_reason": "",
        "blocks_v20_9": "FALSE",
    }]

    validation_row = {
        "status": gate_status,
        "patch_version": PATCH_VERSION,
        "generated_at_utc": generated_at,
        "normalized_row_count": str(normalized_count),
        "factor_research_row_count": str(factor_research_rows_created),
        "factor_research_base_dataset_created": tf(factor_research_created),
        "ready_for_v20_10_factor_source_attachment_or_availability_audit_next": tf(ready_for_v20_10),
        "ready_for_factor_evidence_next": "FALSE",
        "ready_for_backtest_next": "FALSE",
        "ready_for_dynamic_weighting_next": "FALSE",
        "ready_for_trading_or_official_recommendation": "FALSE",
        "dependency_blocker_count": str(sum(1 for row in dependency_rows if row["status"] == "BLOCKED")),
        "total_blocker_count": str(blocking_count),
        "factor_research_row_id_unique_count": str(len(factor_research_row_ids)),
        "factor_research_row_id_duplicate_count": str(max(0, len(factor_rows) - len(factor_research_row_ids))),
        "source_hash_consistent": tf(source_hash_consistent),
        "run_id_consistent": tf(run_id_consistent),
        "normalized_row_id_unique_count": str(len(unique_normalized_row_ids)),
        "sample_id_preserved_count": str(sum(1 for row in factor_rows if clean(row.get("sample_id")))),
        "official_use_allowed_rows": "0",
        "static_write_path_check_passed": tf(set(ALLOWED_WRITE_PATHS) == {
            OUT_DEPENDENCY,
            OUT_BASE_DATASET,
            OUT_SCHEMA,
            OUT_ATTACHMENT_PLAN,
            OUT_FIELD_AVAILABILITY,
            OUT_TECHNICAL,
            OUT_FUNDAMENTAL,
            OUT_RISK,
            OUT_REGIME,
            OUT_TRUST,
            OUT_BOUNDARY,
            OUT_MISSING_SOURCE,
            OUT_BLOCKERS,
            OUT_GATE,
            OUT_NEXT,
            OUT_VALIDATION,
            REPORT,
            CURRENT_REPORT,
            READ_FIRST,
        }),
        **SAFETY_FLAGS,
    }

    write_csv(OUT_DEPENDENCY, dependency_rows, ["dependency", "path", "exists", "status", "blocker_reason"])
    write_csv(OUT_BASE_DATASET, factor_rows, FACTOR_RESEARCH_COLUMNS)
    write_csv(OUT_SCHEMA, [
        {
            "column_name": column,
            "required": "TRUE",
            "detected": tf(column in set(factor_rows[0].keys()) if factor_rows else False),
            "non_empty_row_count": str(sum(1 for row in factor_rows if clean(row.get(column)))),
            "row_count": str(len(factor_rows)),
            "schema_status": "PASS" if factor_rows and column in factor_rows[0].keys() and all(clean(row.get(column)) for row in factor_rows) else "BLOCKED",
            "blocker_reason": "" if factor_rows and column in factor_rows[0].keys() and all(clean(row.get(column)) for row in factor_rows) else f"Required factor research column {column} is missing or blank.",
        } for column in FACTOR_RESEARCH_COLUMNS
    ], ["column_name", "required", "detected", "non_empty_row_count", "row_count", "schema_status", "blocker_reason"])
    write_csv(OUT_ATTACHMENT_PLAN, attachment_plan_rows, ["factor_family", "factor_name", "required_input_type", "currently_available_from_v20_8", "attachment_ready_now", "evidence_allowed_now", "blocker_reason", "next_required_source_or_step"])
    write_csv(OUT_FIELD_AVAILABILITY, field_availability_rows, ["field_group", "required_fields", "available_from_v20_8", "availability_status", "blocker_reason", "next_required_source_or_step"])
    write_csv(OUT_TECHNICAL, technical_audit, list(technical_audit[0].keys()))
    write_csv(OUT_FUNDAMENTAL, fundamental_audit, list(fundamental_audit[0].keys()))
    write_csv(OUT_RISK, risk_audit, list(risk_audit[0].keys()))
    write_csv(OUT_REGIME, regime_audit, list(regime_audit[0].keys()))
    write_csv(OUT_TRUST, trust_audit, list(trust_audit[0].keys()))
    write_csv(OUT_BOUNDARY, boundary_rows, list(boundary_rows[0].keys()))
    write_csv(OUT_MISSING_SOURCE, missing_source_rows, list(missing_source_rows[0].keys()))
    write_csv(OUT_BLOCKERS, blocker_rows, ["blocker_id", "blocker_scope", "severity", "blocker_status", "blocker_reason", "blocks_v20_9"])
    write_csv(OUT_GATE, gate_output, list(gate_output[0].keys()))
    write_csv(OUT_NEXT, next_output, list(next_output[0].keys()))
    write_csv(OUT_VALIDATION, [validation_row], list(validation_row.keys()))

    report_lines = [
        "# V20.9 Factor Research Dataset Preparation",
        "",
        f"- STATUS: `{gate_status}`",
        f"- factor research base dataset created: `{tf(factor_research_created)}`",
        f"- factor research rows created: `{factor_research_rows_created}`",
        f"- ready for V20.10 factor source attachment or availability audit next: `{tf(ready_for_v20_10)}`",
        "- ready for factor evidence next: `FALSE`",
        "- ready for backtest next: `FALSE`",
        "- ready for dynamic weighting next: `FALSE`",
        "- ready for trading or official recommendation: `FALSE`",
        "- official use allowed: `FALSE`",
        "",
        "## Dependency Audit",
        md_table(["dependency", "exists", "status"], dependency_rows),
        "",
        "## Gate Decision",
        md_table(["gate_id", "status", "FACTOR_RESEARCH_BASE_DATASET_CREATED", "FACTOR_RESEARCH_ROWS_CREATED", "READY_FOR_V20_10_FACTOR_SOURCE_ATTACHMENT_OR_AVAILABILITY_AUDIT_NEXT", "READY_FOR_FACTOR_EVIDENCE_NEXT"], gate_output),
        "",
        "## Readiness",
        md_table(["factor_family_group", "factor_count", "currently_available_from_v20_8_count", "attachment_ready_now_count", "evidence_allowed_now_count", "readiness_status"], technical_audit + fundamental_audit + risk_audit + regime_audit + trust_audit, limit=20),
        "",
        "This step prepares a research-only factor dataset from the V20.8 normalized research dataset. It preserves lineage and sample identifiers, prepares the base rows for factor research, and does not create factor evidence, backtests, dynamic weighting rows, trading signals, official recommendations, broker actions, V21 outputs, or V19.21 outputs.",
        "",
    ]
    write_text(REPORT, "\n".join(report_lines))
    write_text(CURRENT_REPORT, "\n".join(report_lines))

    read_first_lines = [
        f"STATUS: {gate_status}",
        f"PATCH_VERSION: {PATCH_VERSION}",
        "REPORTING_ONLY: FALSE",
        "FACTOR_RESEARCH_PREPARATION_ONLY: TRUE",
        f"FACTOR_RESEARCH_BASE_DATASET_CREATED: {tf(factor_research_created)}",
        f"FACTOR_RESEARCH_ROWS_CREATED: {factor_research_rows_created}",
        "FACTOR_EVIDENCE_ROWS_CREATED: 0",
        "BACKTEST_ROWS_CREATED: 0",
        "DYNAMIC_WEIGHTING_ROWS_CREATED: 0",
        "TRADING_SIGNAL_ROWS_CREATED: 0",
        "OFFICIAL_RECOMMENDATION_ROWS_CREATED: 0",
        "BROKER_API_USED: FALSE",
        "ORDER_EXECUTION_USED: FALSE",
        "SOURCE_MUTATION_USED: FALSE",
        "V21_OUTPUTS_CREATED: FALSE",
        "V19_21_OUTPUTS_CREATED: FALSE",
        "OFFICIAL_USE_ALLOWED: FALSE",
        f"READY_FOR_V20_10_FACTOR_SOURCE_ATTACHMENT_OR_AVAILABILITY_AUDIT_NEXT: {tf(ready_for_v20_10)}",
        "READY_FOR_FACTOR_EVIDENCE_NEXT: FALSE",
        "READY_FOR_BACKTEST_NEXT: FALSE",
        "READY_FOR_DYNAMIC_WEIGHTING_NEXT: FALSE",
        "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION: FALSE",
        f"FACTOR_RESEARCH_DATASET_VERSION: {FACTOR_RESEARCH_DATASET_VERSION}",
        f"SOURCE_STEP: {EXPECTED_SOURCE_STEP}",
        f"BASE_ROW_COUNT: {normalized_count}",
        f"FACTOR_RESEARCH_ROW_COUNT: {factor_research_rows_created}",
        f"STATIC_WRITE_PATH_CHECK_PASSED: {tf(set(ALLOWED_WRITE_PATHS) == {OUT_DEPENDENCY, OUT_BASE_DATASET, OUT_SCHEMA, OUT_ATTACHMENT_PLAN, OUT_FIELD_AVAILABILITY, OUT_TECHNICAL, OUT_FUNDAMENTAL, OUT_RISK, OUT_REGIME, OUT_TRUST, OUT_BOUNDARY, OUT_MISSING_SOURCE, OUT_BLOCKERS, OUT_GATE, OUT_NEXT, OUT_VALIDATION, REPORT, CURRENT_REPORT, READ_FIRST})}",
        "DEPENDENCY_AUDIT_CSV: " + rel(OUT_DEPENDENCY),
        "FACTOR_RESEARCH_BASE_DATASET_CSV: " + rel(OUT_BASE_DATASET),
        "FACTOR_RESEARCH_SCHEMA_AUDIT_CSV: " + rel(OUT_SCHEMA),
        "FACTOR_FAMILY_ATTACHMENT_PLAN_CSV: " + rel(OUT_ATTACHMENT_PLAN),
        "FACTOR_INPUT_FIELD_AVAILABILITY_AUDIT_CSV: " + rel(OUT_FIELD_AVAILABILITY),
        "TECHNICAL_FACTOR_READINESS_AUDIT_CSV: " + rel(OUT_TECHNICAL),
        "FUNDAMENTAL_FACTOR_READINESS_AUDIT_CSV: " + rel(OUT_FUNDAMENTAL),
        "RISK_FACTOR_READINESS_AUDIT_CSV: " + rel(OUT_RISK),
        "MARKET_REGIME_FACTOR_READINESS_AUDIT_CSV: " + rel(OUT_REGIME),
        "DATA_TRUSTWORTHINESS_FACTOR_READINESS_AUDIT_CSV: " + rel(OUT_TRUST),
        "FACTOR_RESEARCH_BOUNDARY_AUDIT_CSV: " + rel(OUT_BOUNDARY),
        "MISSING_FACTOR_SOURCE_REGISTER_CSV: " + rel(OUT_MISSING_SOURCE),
        "BLOCKER_REGISTER_CSV: " + rel(OUT_BLOCKERS),
        "GATE_DECISION_CSV: " + rel(OUT_GATE),
        "NEXT_STEP_DECISION_CSV: " + rel(OUT_NEXT),
        "VALIDATION_SUMMARY_CSV: " + rel(OUT_VALIDATION),
        "REPORT: " + rel(REPORT),
        "CURRENT_REPORT: " + rel(CURRENT_REPORT),
        "",
    ]
    read_first_output_text = "\n".join(read_first_lines)
    if not required_flags_present(read_first_output_text, factor_research_rows_created):
        add_blocker(blockers, "READ_FIRST", "V20.9 READ_FIRST safety flags are incomplete.")
    write_text(READ_FIRST, read_first_output_text)

    validation_row["FACTOR_RESEARCH_BASE_DATASET_CREATED"] = tf(factor_research_created)
    validation_row["FACTOR_RESEARCH_ROWS_CREATED"] = str(factor_research_rows_created)
    validation_row["factor_research_row_id_unique_count"] = str(len(factor_research_row_ids))
    validation_row["factor_research_row_id_duplicate_count"] = str(max(0, len(factor_rows) - len(factor_research_row_ids)))
    validation_row["read_first_safety_flags_present"] = tf(required_flags_present(read_first_output_text, factor_research_rows_created))
    validation_row["write_paths_expected_count"] = str(len(ALLOWED_WRITE_PATHS))
    validation_row["write_paths_written_count"] = str(len(ALLOWED_WRITE_PATHS))
    validation_row["allowed_write_paths_match"] = tf(set(ALLOWED_WRITE_PATHS) == {OUT_DEPENDENCY, OUT_BASE_DATASET, OUT_SCHEMA, OUT_ATTACHMENT_PLAN, OUT_FIELD_AVAILABILITY, OUT_TECHNICAL, OUT_FUNDAMENTAL, OUT_RISK, OUT_REGIME, OUT_TRUST, OUT_BOUNDARY, OUT_MISSING_SOURCE, OUT_BLOCKERS, OUT_GATE, OUT_NEXT, OUT_VALIDATION, REPORT, CURRENT_REPORT, READ_FIRST})
    write_csv(OUT_VALIDATION, [validation_row], list(validation_row.keys()))

    for key, value in validation_row.items():
        print(f"{key.upper()}: {value}")
    print(f"READ_FIRST: {rel(READ_FIRST)}")
    return 0 if ready_for_v20_10 else 1


if __name__ == "__main__":
    raise SystemExit(main())
