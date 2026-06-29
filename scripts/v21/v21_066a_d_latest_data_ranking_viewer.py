#!/usr/bin/env python
"""Read-only latest-data ranking viewer for D_WEIGHT_OPTIMIZED_R1."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import pandas as pd


STAGE_ID = "V21.066A"
SOURCE_VARIANT = "D_WEIGHT_OPTIMIZED_R1"
BASE_WEIGHT = 0.60
MOMENTUM_WEIGHT = 0.40
OUT_REL = Path(
    "outputs/v21/experiments/momentum_dynamic/d_weight_optimized/"
    "v21_066a_latest_data_ranking_viewer"
)
TOP20_NAME = "V21_066A_D_LATEST_RANKING_TOP20.csv"
TOP50_NAME = "V21_066A_D_LATEST_RANKING_TOP50.csv"
FULL_NAME = "V21_066A_D_LATEST_RANKING_FULL.csv"
SUMMARY_NAME = "V21_066A_D_LATEST_RANKING_SUMMARY.csv"
AUDIT_NAME = "V21_066A_D_LATEST_RANKING_AUDIT.json"
VALIDATION_NAME = "V21_066A_D_LATEST_RANKING_VALIDATION.json"
COMPONENT_REL = Path(
    "outputs/v21/experiments/momentum_dynamic/"
    "V21_059_R1_VARIANT_SCORE_COMPONENTS.csv"
)
METADATA_REL = Path(
    "outputs/v18/universe/V18_CURRENT_UNIVERSE_ROLLING_STATE.csv"
)

PERSISTED_STATUS = "PASS_V21_066A_D_LATEST_PERSISTED_RANKING_VIEW_READY"
PERSISTED_DECISION = "D_RANKING_VIEW_READY_PERSISTED_SOURCE_ONLY"
RECOMPUTED_STATUS = (
    "PASS_V21_066A_D_LATEST_DATA_RECOMPUTED_RANKING_VIEW_READY"
)
RECOMPUTED_DECISION = "D_LATEST_DATA_RANKING_VIEW_READY_RESEARCH_ONLY"

OUTPUT_FIELDS = [
    "rank", "ticker", "company_name", "sector", "industry",
    "source_variant", "final_score", "base_score", "momentum_score",
    "weighted_base_component", "weighted_momentum_component",
    "base_weight", "momentum_weight", "eligible_flag", "exclusion_reason",
    "latest_price_date", "price_date_warning", "risk_label",
    "exhaustion_label", "rank_bucket", "research_only",
]


def clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def truth(value: object) -> bool:
    return clean(value).upper() == "TRUE"


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def discover_d_source(root: Path) -> tuple[Path, Path, dict[str, object]]:
    base = root / "outputs/v21/experiments/momentum_dynamic"
    candidates = sorted(
        base.rglob("V21_060_R5_SUMMARY.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for summary_path in candidates:
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        ranking = summary_path.parent / (
            "V21_060_R5_D_WEIGHT_OPTIMIZED_RANKING.csv"
        )
        if (
            summary.get("proposed_variant_id") == SOURCE_VARIANT
            and summary.get("research_only") is True
            and summary.get("official_mutation_detected") is False
            and ranking.is_file()
        ):
            return summary_path, ranking, summary
    raise RuntimeError("No valid V21.060-R5 D ranking source found.")


def discover_price_files(root: Path) -> list[Path]:
    files = []
    for base in (
        root / "inputs/v21/historical_ohlcv_cache",
        root / "outputs/v20/price_history",
    ):
        if base.exists():
            files.extend(base.glob("*OHLCV*.csv"))
    return sorted(set(path.resolve() for path in files if path.is_file()))


def latest_prices(
    root: Path, tickers: set[str]
) -> tuple[dict[str, str], str, list[str]]:
    latest_by_ticker: dict[str, str] = {}
    used = []
    for path in discover_price_files(root):
        try:
            columns = set(pd.read_csv(path, nrows=0).columns)
            ticker_col = "ticker" if "ticker" in columns else "symbol"
            date_col = "as_of_date" if "as_of_date" in columns else "date"
            if ticker_col not in columns or date_col not in columns:
                continue
            frame = pd.read_csv(path, usecols=[ticker_col, date_col], low_memory=False)
        except (OSError, ValueError):
            continue
        frame[ticker_col] = frame[ticker_col].astype(str).str.upper().str.strip()
        frame[date_col] = frame[date_col].astype(str).str.slice(0, 10)
        frame = frame[frame[ticker_col].isin(tickers)]
        if frame.empty:
            continue
        for ticker, group in frame.groupby(ticker_col):
            latest_by_ticker[ticker] = max(
                latest_by_ticker.get(ticker, ""), clean(group[date_col].max())
            )
        used.append(relative(root, path))
    return latest_by_ticker, max(latest_by_ticker.values(), default=""), used


def metadata_map(root: Path) -> dict[str, dict[str, str]]:
    rows = read_csv(root / METADATA_REL)
    output = {}
    for row in rows:
        ticker = clean(row.get("ticker")).upper()
        if ticker and ticker not in output:
            output[ticker] = {
                "company_name": clean(row.get("company_name")),
                "sector": clean(row.get("sector")),
                "industry": clean(row.get("industry")),
            }
    return output


def recompute_from_components(root: Path) -> pd.DataFrame | None:
    path = root / COMPONENT_REL
    if not path.is_file():
        return None
    frame = pd.read_csv(path, low_memory=False)
    frame = frame[frame["variant_id"] == "B_MOMENTUM_STATIC_R1"].copy()
    if frame.empty:
        return None
    frame["base_score"] = pd.to_numeric(frame["base_score"], errors="coerce")
    frame["momentum_score"] = pd.to_numeric(
        frame["momentum_score"], errors="coerce"
    )
    eligible = (
        frame["eligible_for_variant_ranking"].astype(str).str.upper().eq("TRUE")
        & frame["base_score"].notna()
        & frame["momentum_score"].notna()
        & frame["price_available"].astype(str).str.upper().eq("TRUE")
        & ~frame["entered_by_forced_audit_only"].astype(str).str.upper().eq("TRUE")
        & ~frame["newly_listed_policy_bucket"].astype(str).isin(
            ["LOCAL_PRICE_NOT_FOUND", "TRUE_IPO_EARLY_WATCH"]
        )
    )
    frame["variant_id"] = SOURCE_VARIANT
    frame["eligible_for_variant_ranking"] = eligible.map(
        {True: "TRUE", False: "FALSE"}
    )
    frame["variant_exclusion_reason"] = (
        frame["variant_exclusion_reason"].fillna("")
    )
    frame.loc[
        ~eligible & frame["variant_exclusion_reason"].eq(""),
        "variant_exclusion_reason",
    ] = "D_ELIGIBILITY_OR_DATA_POLICY_EXCLUDED"
    frame["final_shadow_score"] = (
        frame["base_score"] * BASE_WEIGHT
        + frame["momentum_score"] * MOMENTUM_WEIGHT
    )
    frame.loc[~eligible, "final_shadow_score"] = pd.NA
    frame["final_shadow_rank"] = pd.NA
    frame.loc[eligible, "final_shadow_rank"] = (
        frame.loc[eligible, "final_shadow_score"]
        .rank(method="first", ascending=False)
        .astype(int)
    )
    frame["research_only"] = "TRUE"
    return frame.sort_values(
        ["eligible_for_variant_ranking", "final_shadow_rank"],
        ascending=[False, True],
    )


def ranking_signature(frame: pd.DataFrame) -> list[tuple[str, int, str]]:
    eligible = frame[
        frame["eligible_for_variant_ranking"].astype(str).str.upper().eq("TRUE")
    ].copy()
    eligible["rank_num"] = pd.to_numeric(
        eligible["final_shadow_rank"], errors="coerce"
    ).astype(int)
    eligible = eligible.sort_values("rank_num")
    return [
        (clean(row["ticker"]).upper(), int(row["rank_num"]), f"{float(row['final_shadow_score']):.10f}")
        for _, row in eligible.iterrows()
    ]


def protected_paths(root: Path, source_dir: Path) -> list[Path]:
    paths = list(source_dir.glob("V21_060_R5_*"))
    base = root / "outputs/v21/experiments/momentum_dynamic"
    for pattern in (
        "V21_060_R1_ABCD_*", "V21_061_R1_*", "V21_062_R1_*",
        "d_weight_optimized/v21_062_daily_monitoring/V21_062_D_*",
        "d_weight_optimized/v21_063_maturity_refresh_and_abcd_comparison_readiness/V21_063_*",
        "d_weight_optimized/v21_064_daily_maturity_continuation_or_price_refresh_check/V21_064_*",
        "d_weight_optimized/v21_065_price_refresh_then_d_maturity_recheck/V21_065_*",
        "d_weight_optimized/v21_066_maturity_wait_continuation_after_price_refresh/V21_066_*",
    ):
        paths.extend(base.glob(pattern))
    output_dir = (root / OUT_REL).resolve()
    for scan_root in (root / "outputs", root / "data"):
        if not scan_root.exists():
            continue
        for path in scan_root.rglob("*"):
            if not path.is_file() or output_dir in path.resolve().parents:
                continue
            text = path.as_posix().lower()
            if (
                ("official" in text and any(
                    token in text
                    for token in ("rank", "weight", "recommend", "allocation")
                ))
                or "real_book" in text or "realbook" in text or "broker" in text
            ):
                paths.append(path)
    return sorted({path.resolve() for path in paths if path.is_file()})


def viewer_rows(
    frame: pd.DataFrame,
    prices: dict[str, str],
    metadata: dict[str, dict[str, str]],
) -> list[dict[str, object]]:
    rows = []
    for _, source in frame.iterrows():
        ticker = clean(source.get("ticker")).upper()
        rank_value = pd.to_numeric(source.get("final_shadow_rank"), errors="coerce")
        rank = "" if pd.isna(rank_value) else int(rank_value)
        eligible = clean(source.get("eligible_for_variant_ranking")).upper() == "TRUE"
        as_of = clean(source.get("as_of_date"))[:10]
        latest = prices.get(ticker, "")
        warning = not latest or (as_of and latest < as_of)
        exhaustion = pd.to_numeric(
            source.get("exhaustion_risk_score"), errors="coerce"
        )
        if pd.isna(exhaustion):
            exhaustion_label = ""
        elif exhaustion >= 60:
            exhaustion_label = "HIGH_EXHAUSTION"
        elif exhaustion >= 40:
            exhaustion_label = "MODERATE_EXHAUSTION"
        else:
            exhaustion_label = "LOW_EXHAUSTION"
        instrument = clean(source.get("instrument_type"))
        risk_label = "|".join(filter(None, [
            instrument if "ETF" in instrument else "",
            clean(source.get("risk_size_bucket")),
            clean(source.get("chase_permission")),
        ]))
        info = metadata.get(ticker, {})
        rows.append({
            "rank": rank,
            "ticker": ticker,
            "company_name": info.get("company_name", ""),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "source_variant": SOURCE_VARIANT,
            "final_score": clean(source.get("final_shadow_score")),
            "base_score": clean(source.get("base_score")),
            "momentum_score": clean(source.get("momentum_score")),
            "weighted_base_component": (
                f"{float(source['base_score']) * BASE_WEIGHT:.10f}"
                if not pd.isna(source.get("base_score")) else ""
            ),
            "weighted_momentum_component": (
                f"{float(source['momentum_score']) * MOMENTUM_WEIGHT:.10f}"
                if not pd.isna(source.get("momentum_score")) else ""
            ),
            "base_weight": BASE_WEIGHT,
            "momentum_weight": MOMENTUM_WEIGHT,
            "eligible_flag": eligible,
            "exclusion_reason": clean(source.get("variant_exclusion_reason")),
            "latest_price_date": latest,
            "price_date_warning": warning,
            "risk_label": risk_label,
            "exhaustion_label": exhaustion_label,
            "rank_bucket": (
                "TOP20" if isinstance(rank, int) and rank <= 20
                else "TOP50" if isinstance(rank, int) and rank <= 50
                else ""
            ),
            "research_only": True,
        })
    return rows


def run_stage(root: Path) -> dict[str, object]:
    root = root.resolve()
    output_dir = root / OUT_REL
    output_dir.mkdir(parents=True, exist_ok=True)
    source_summary_path, source_ranking_path, source_summary = discover_d_source(root)
    persisted = pd.read_csv(source_ranking_path, low_memory=False)
    protected = protected_paths(root, source_summary_path.parent)
    before = {relative(root, path): sha256(path) for path in protected}

    errors = []
    if persisted.empty:
        errors.append("SOURCE_RANKING_EMPTY")
    if set(persisted["variant_id"].dropna().astype(str)) != {SOURCE_VARIANT}:
        errors.append("SOURCE_VARIANT_MISMATCH")
    if not persisted["research_only"].astype(str).str.upper().eq("TRUE").all():
        errors.append("SOURCE_RESEARCH_ONLY_FALSE")
    if int(source_summary.get("local_price_missing_ranked_violation_count", 0)):
        errors.append("SOURCE_MISSING_PRICE_RANKING_VIOLATION")
    if int(source_summary.get("tqqq_ipo_watch_violation_count", 0)):
        errors.append("SOURCE_TQQQ_IPO_WATCH_VIOLATION")
    leverage_violations = (
        int(source_summary.get("leveraged_full_size_violation_count", 0))
        + int(source_summary.get("inverse_non_hedge_violation_count", 0))
    )
    if leverage_violations:
        errors.append("SOURCE_LEVERAGED_INVERSE_RISK_VIOLATION")

    tickers = set(persisted["ticker"].astype(str).str.upper().str.strip())
    prices, latest_available, price_sources = latest_prices(root, tickers)
    source_price_date = clean(persisted["as_of_date"].astype(str).str[:10].max())
    recomputed = recompute_from_components(root)
    recomputed_ok = (
        recomputed is not None
        and latest_available >= source_price_date
        and ranking_signature(recomputed) == ranking_signature(persisted)
    )
    selected = recomputed if recomputed_ok else persisted
    rows = viewer_rows(selected, prices, metadata_map(root))
    eligible = sorted(
        (row for row in rows if row["eligible_flag"]),
        key=lambda row: int(row["rank"]),
    )
    top20 = eligible[:20]
    top50 = eligible[:50]
    warning_count = sum(bool(row["price_date_warning"]) for row in rows)
    leveraged_inverse_top20 = sum(
        "LEVERAGED" in clean(row["risk_label"])
        or "INVERSE" in clean(row["risk_label"])
        for row in top20
    )
    high_exhaustion_top20 = sum(
        row["exhaustion_label"] == "HIGH_EXHAUSTION" for row in top20
    )
    if len({row["rank"] for row in eligible}) != len(eligible):
        errors.append("DUPLICATE_ELIGIBLE_RANKS")
    if any(not row["ticker"] for row in rows):
        errors.append("EMPTY_TICKER")

    if errors:
        final_status = "BLOCKED_V21_066A_D_RANKING_INPUT_CONTRACT_FAILURE"
        decision = "D_RANKING_VIEW_BLOCKED_INPUT_REVIEW_REQUIRED"
    elif recomputed_ok:
        final_status = RECOMPUTED_STATUS
        decision = RECOMPUTED_DECISION
    else:
        final_status = PERSISTED_STATUS
        decision = PERSISTED_DECISION
    summary = {
        "final_status": final_status,
        "decision": decision,
        "source_stage": clean(source_summary.get("stage_id")),
        "source_variant": SOURCE_VARIANT,
        "recomputed_latest_data": recomputed_ok,
        "ranking_source_file": relative(root, source_ranking_path),
        "ranking_source_price_date": source_price_date,
        "latest_available_price_date": latest_available,
        "total_ranking_rows": len(rows),
        "eligible_count": len(eligible),
        "excluded_count": len(rows) - len(eligible),
        "top20_count": len(top20),
        "top50_count": len(top50),
        "price_date_warning_count": warning_count,
        "missing_price_ranking_violations": int(
            source_summary.get("local_price_missing_ranked_violation_count", 0)
        ),
        "leveraged_inverse_top20_count": leveraged_inverse_top20,
        "high_exhaustion_top20_count": high_exhaustion_top20,
        "official_mutation": False,
        "research_only": True,
        "trade_action_created": False,
        "recommendation_allowed": False,
        "protected_outputs_modified": False,
        "recommended_next_stage": "V21_067_D_TARGET_DATE_RECHECK_GATE",
    }
    write_csv(output_dir / FULL_NAME, rows, OUTPUT_FIELDS)
    write_csv(output_dir / TOP20_NAME, top20, OUTPUT_FIELDS)
    write_csv(output_dir / TOP50_NAME, top50, OUTPUT_FIELDS)
    write_csv(output_dir / SUMMARY_NAME, [summary], list(summary.keys()))

    after = {path: sha256(root / path) for path in before}
    changed = sorted(path for path in before if before[path] != after[path])
    validation = {
        "stage_id": STAGE_ID,
        "source_summary_path": relative(root, source_summary_path),
        "source_ranking_path": relative(root, source_ranking_path),
        "source_variant_valid": not any(
            error == "SOURCE_VARIANT_MISMATCH" for error in errors
        ),
        "recomputation_attempted": recomputed is not None,
        "recomputed_latest_data": recomputed_ok,
        "recomputed_persisted_rank_signature_match": (
            recomputed is not None
            and ranking_signature(recomputed) == ranking_signature(persisted)
        ),
        "eligible_ranks_unique": len({row["rank"] for row in eligible}) == len(eligible),
        "tickers_non_null": all(row["ticker"] for row in rows),
        "base_weight_valid": all(
            abs(float(row["base_weight"]) - BASE_WEIGHT) < 1e-12 for row in rows
        ),
        "momentum_weight_valid": all(
            abs(float(row["momentum_weight"]) - MOMENTUM_WEIGHT) < 1e-12 for row in rows
        ),
        "top20_count_valid": len(top20) == min(20, len(eligible)),
        "top50_count_valid": len(top50) == min(50, len(eligible)),
        "official_ranking_mutation": False,
        "official_recommendation_mutation": False,
        "broker_output_mutation": False,
        "trade_action_created": False,
        "abcd_ledger_mutation": False,
        "protected_outputs_modified": changed,
        "official_mutation": False,
        "recommendation_allowed": False,
        "research_only": True,
        "contract_errors": errors,
    }
    audit = {
        "stage_id": STAGE_ID,
        "run_contract": "READ_ONLY_D_RANKING_VIEWER",
        "ranking_source_file": relative(root, source_ranking_path),
        "ranking_source_sha256": before[relative(root, source_ranking_path)],
        "score_component_source": relative(root, root / COMPONENT_REL),
        "ranking_source_price_date": source_price_date,
        "latest_available_price_date": latest_available,
        "price_sources_checked": price_sources,
        "recomputed_latest_data": recomputed_ok,
        "recomputation_basis": (
            "IN_MEMORY_V21_060_R5_FORMULA_FROM_V21_059_COMPONENTS_"
            "WITH_EXACT_PERSISTED_RANK_RECONCILIATION"
            if recomputed_ok
            else "PERSISTED_RANKING_ONLY_SAFE_RECOMPUTATION_NOT_VALIDATED"
        ),
        "protected_before_sha256": before,
        "protected_after_sha256": after,
        "protected_outputs_modified": changed,
        "guardrails": {
            "alpha_evaluated": False,
            "abcd_performance_compared": False,
            "preferred_policy_selected": False,
            "weights_optimized": False,
            "forward_returns_computed": False,
            "official_use": False,
        },
        "research_only": True,
    }
    write_json(output_dir / AUDIT_NAME, audit)
    write_json(output_dir / VALIDATION_NAME, validation)

    final_after = {path: sha256(root / path) for path in before}
    final_changed = sorted(
        path for path in before if before[path] != final_after[path]
    )
    if final_changed:
        summary["final_status"] = "BLOCKED_V21_066A_PROTECTED_OUTPUT_MUTATION"
        summary["decision"] = "RESTORE_PROTECTED_OUTPUTS_BEFORE_VIEWING"
        summary["official_mutation"] = True
        summary["protected_outputs_modified"] = True
        validation["protected_outputs_modified"] = final_changed
        write_csv(output_dir / SUMMARY_NAME, [summary], list(summary.keys()))
        write_json(output_dir / VALIDATION_NAME, validation)
    return summary, top20, top50


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    summary, top20, top50 = run_stage(parser.parse_args().root)
    print(f"FINAL_STATUS={summary['final_status']}")
    print(f"DECISION={summary['decision']}")
    print(f"SOURCE_VARIANT={summary['source_variant']}")
    print(f"RECOMPUTED_LATEST_DATA={str(summary['recomputed_latest_data']).upper()}")
    print(f"RANKING_SOURCE_PRICE_DATE={summary['ranking_source_price_date']}")
    print(f"LATEST_AVAILABLE_PRICE_DATE={summary['latest_available_price_date']}")
    print(f"TOTAL_RANKING_ROWS={summary['total_ranking_rows']}")
    print(f"ELIGIBLE/EXCLUDED={summary['eligible_count']}/{summary['excluded_count']}")
    print("TOP20_TICKERS=" + ",".join(row["ticker"] for row in top20))
    print("TOP50_TICKERS=" + ",".join(row["ticker"] for row in top50))
    print(f"PRICE_DATE_WARNINGS={summary['price_date_warning_count']}")
    print(f"OFFICIAL_MUTATION={str(summary['official_mutation']).upper()}")
    print(f"RESEARCH_ONLY={str(summary['research_only']).upper()}")
    print(f"OUTPUT_DIRECTORY={OUT_REL.as_posix()}")
    print(f"NEXT_RECOMMENDED_STAGE={summary['recommended_next_stage']}")
    return 1 if summary["final_status"].startswith("BLOCKED_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
