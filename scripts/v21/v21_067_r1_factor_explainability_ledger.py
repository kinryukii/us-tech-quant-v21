#!/usr/bin/env python
"""V21.067-R1 research-only factor explainability ledger for D ranking."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


STAGE = "V21.067-R1_FACTOR_EXPLAINABILITY_LEDGER"
VARIANT = "D_WEIGHT_OPTIMIZED_R1"
BASE_WEIGHT = 0.60
MOMENTUM_WEIGHT = 0.40
OUT_REL = Path("outputs/v21/explainability")
LEDGER_NAME = "V21_067_R1_FACTOR_EXPLAINABILITY_LEDGER.csv"
SUMMARY_NAME = "V21_067_R1_TOP_BUCKET_EXPLAINABILITY_SUMMARY.csv"
VALIDATION_NAME = "V21_067_R1_VALIDATION_SUMMARY.csv"

FAMILIES = (
    "fundamental", "technical", "strategy", "risk", "market_regime",
    "data_trust",
)
SUBFACTORS = (
    "rsi", "kdj", "macd", "bb", "ma20", "ma50", "ema", "volume",
    "volatility", "relative_strength", "breakout", "pullback",
)
CORE_COLUMNS = [
    "run_id", "generated_at_utc", "source_ranking_path",
    "source_ranking_hash", "variant", "research_only", "official_mutation",
    "protected_outputs_modified", "ticker", "rank", "final_score",
    "eligible_flag", "exclusion_reason", "base_weight", "momentum_weight",
    "base_score_raw", "momentum_score_raw", "base_contribution",
    "momentum_contribution", "reconstructed_score", "reconstruction_error",
    "reconstruction_status", "positive_driver_1", "positive_driver_2",
    "positive_driver_3", "negative_driver_1", "negative_driver_2",
    "negative_driver_3", "primary_ranking_reason", "explainability_quality",
    "missing_component_warning",
]
FAMILY_COLUMNS = [
    item
    for family in FAMILIES
    for item in (f"{family}_score_raw", f"{family}_contribution")
]
SUBFACTOR_COLUMNS = [f"technical__{name}" for name in SUBFACTORS]
LEDGER_COLUMNS = CORE_COLUMNS + FAMILY_COLUMNS + SUBFACTOR_COLUMNS
SUMMARY_COLUMNS = [
    "bucket", "row_count", "avg_final_score", "avg_base_contribution",
    "avg_momentum_contribution", "avg_reconstruction_error",
    "momentum_led_count", "base_led_count", "partial_explainability_count",
    "data_trust_warning_count", "risk_warning_count",
    "top_positive_driver_1", "top_positive_driver_2",
    "top_positive_driver_3", "top_negative_driver_1",
    "top_negative_driver_2", "top_negative_driver_3",
]


def utc_now() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y%m%dT%H%M%SZ"), now.isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def truth_series(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.upper().isin(
        {"TRUE", "1", "YES", "Y"}
    )


def first_column(frame: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    lookup = {str(column).lower(): str(column) for column in frame.columns}
    return next((lookup[name.lower()] for name in names if name.lower() in lookup), None)


def normalized_ranking(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    aliases = {
        "ticker": ("ticker", "symbol"),
        "rank": ("rank", "final_shadow_rank", "final_rank"),
        "final_score": ("final_score", "final_shadow_score", "score"),
        "base_score": ("base_score", "base_ranking_score"),
        "momentum_score": ("momentum_score",),
        "base_contribution": ("weighted_base_component", "base_contribution"),
        "momentum_contribution": (
            "weighted_momentum_component", "momentum_contribution"
        ),
        "base_weight": ("base_weight",),
        "momentum_weight": ("momentum_weight", "applied_momentum_weight"),
        "eligible": ("eligible_flag", "eligible_for_variant_ranking"),
        "exclusion": ("exclusion_reason", "variant_exclusion_reason"),
        "variant": ("source_variant", "variant_id", "variant"),
        "research_only": ("research_only",),
    }
    result = pd.DataFrame(index=frame.index)
    for target, names in aliases.items():
        source = first_column(frame, names)
        result[target] = frame[source] if source else pd.NA
    result["ticker"] = result["ticker"].astype("string").str.strip().str.upper()
    for column in (
        "rank", "final_score", "base_score", "momentum_score",
        "base_contribution", "momentum_contribution", "base_weight",
        "momentum_weight",
    ):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result["eligible"] = truth_series(result["eligible"])
    result["research_only"] = truth_series(result["research_only"])
    result["variant"] = result["variant"].astype("string").fillna("")
    result["exclusion"] = result["exclusion"].astype("string").fillna("")
    return result


def candidate_valid(path: Path) -> tuple[bool, pd.DataFrame | None]:
    try:
        frame = normalized_ranking(path)
    except (OSError, ValueError, KeyError):
        return False, None
    if frame.empty or frame["ticker"].isna().any():
        return False, None
    if not frame["research_only"].all():
        return False, None
    variants = set(frame["variant"].dropna().astype(str))
    if variants and variants != {VARIANT}:
        return False, None
    if frame["rank"].isna().all() or frame["final_score"].isna().all():
        return False, None
    return True, frame


def discover_ranking(root: Path, override: Path | None = None) -> tuple[Path, pd.DataFrame]:
    if override is not None:
        path = override if override.is_absolute() else root / override
        valid, frame = candidate_valid(path)
        if valid and frame is not None:
            return path.resolve(), frame
        raise FileNotFoundError("No valid research-only D ranking at override path")

    preferred = list((root / "outputs/v21").rglob("V21_066A_D_LATEST_RANKING_FULL.csv"))
    fallback = list((root / "outputs/v21").rglob("*D*RANKING*.csv"))
    candidates = sorted(
        set(preferred + fallback),
        key=lambda path: (
            1 if path.name == "V21_066A_D_LATEST_RANKING_FULL.csv" else 0,
            path.stat().st_mtime,
        ),
        reverse=True,
    )
    for path in candidates:
        valid, frame = candidate_valid(path)
        if valid and frame is not None:
            return path.resolve(), frame
    raise FileNotFoundError("No valid research-only V21 D ranking input found")


def protected_paths(root: Path, source: Path | None, output_dir: Path) -> list[Path]:
    paths: set[Path] = set()
    if source and source.is_file():
        paths.add(source.resolve())
    for base in (root / "outputs", root / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or output_dir.resolve() in path.resolve().parents:
                continue
            text = path.as_posix().lower()
            if (
                "forward_observation_ledger" in text
                or "official" in text
                or "broker" in text
                or "protected" in text
                or "066a_d_latest_ranking" in text
                or "060_r5_d_weight_optimized_ranking" in text
            ):
                paths.add(path.resolve())
    return sorted(paths)


def snapshot(paths: list[Path]) -> dict[str, str]:
    return {str(path): sha256(path) for path in paths if path.is_file()}


def supplemental_components(
    root: Path, ranking_path: Path, tickers: set[str]
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    aliases: dict[str, tuple[str, ...]] = {
        **{f"{family}_score_raw": (f"{family}_score", f"{family}_score_raw")
           for family in FAMILIES},
        **{f"{family}_weight": (f"{family}_weight",) for family in FAMILIES},
        **{f"technical__{name}": (
            f"technical__{name}", f"technical_{name}", f"{name}_score"
        ) for name in SUBFACTORS},
    }
    aliases["risk_score_raw"] += ("risk_penalty", "exhaustion_risk_score")
    aliases["data_trust_score_raw"] += ("data_trust_score", "trust_score")
    collected: dict[str, dict[str, Any]] = {ticker: {} for ticker in tickers}
    sources: dict[str, str] = {}
    files = sorted(
        (
            path for path in (root / "outputs/v21").rglob("*.csv")
            if path.resolve() != ranking_path.resolve()
            and OUT_REL.as_posix() not in path.as_posix()
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    unresolved = set(aliases)
    for path in files:
        if not unresolved:
            break
        try:
            columns = list(pd.read_csv(path, nrows=0).columns)
        except (OSError, ValueError):
            continue
        ticker_col = next(
            (column for column in columns if str(column).lower() in {"ticker", "symbol"}),
            None,
        )
        matches = {
            target: next(
                (column for column in columns
                 if str(column).lower() in {name.lower() for name in aliases[target]}),
                None,
            )
            for target in unresolved
        }
        matches = {target: column for target, column in matches.items() if column}
        if not ticker_col or not matches:
            continue
        try:
            frame = pd.read_csv(
                path, usecols=[ticker_col, *set(matches.values())], low_memory=False
            )
        except (OSError, ValueError):
            continue
        frame[ticker_col] = frame[ticker_col].astype(str).str.strip().str.upper()
        frame = frame[frame[ticker_col].isin(tickers)].drop_duplicates(ticker_col, keep="last")
        if frame.empty:
            continue
        for target, column in matches.items():
            numeric = pd.to_numeric(frame[column], errors="coerce")
            if not numeric.notna().any():
                continue
            for ticker, value in zip(frame[ticker_col], numeric):
                if pd.notna(value) and target not in collected[ticker]:
                    collected[ticker][target] = float(value)
            if any(target in values for values in collected.values()):
                sources[target] = relative(root, path)
                unresolved.discard(target)
    return collected, sources


def driver_labels(row: dict[str, Any]) -> tuple[list[str], list[str]]:
    base = row.get("base_contribution")
    momentum = row.get("momentum_contribution")
    positives: list[tuple[float, str]] = []
    negatives: list[tuple[float, str]] = []
    if pd.notna(momentum):
        positives.append((float(momentum), "MOMENTUM_STRONG"))
    if pd.notna(base):
        positives.append((float(base), "BASE_SCORE_STRONG"))
    subfactor_labels = {
        "technical__relative_strength": "RELATIVE_STRENGTH_STRONG",
        "technical__ma20": "TECHNICAL_TREND_STRONG",
        "technical__ma50": "TECHNICAL_TREND_STRONG",
        "technical__breakout": "TECHNICAL_TREND_STRONG",
    }
    for column, label in subfactor_labels.items():
        value = row.get(column)
        if pd.notna(value):
            positives.append((float(value), label))
    risk = row.get("risk_score_raw")
    if pd.notna(risk) and float(risk) >= 40:
        negatives.append((float(risk), "RISK_PENALTY_HIGH"))
    trust = row.get("data_trust_score_raw")
    if pd.notna(trust) and float(trust) < 50:
        negatives.append((50 - float(trust), "DATA_TRUST_WARNING"))
    volatility = row.get("technical__volatility")
    if pd.notna(volatility) and float(volatility) >= 60:
        negatives.append((float(volatility), "OVERHEAT_WARNING"))
    if row["explainability_quality"] == "PARTIAL":
        negatives.extend([
            (1.0, "COMPONENTS_PARTIAL"),
            (0.9, "LOW_EXPLAINABILITY_COMPONENT_COVERAGE"),
        ])
    positives = sorted(positives, key=lambda item: (-item[0], item[1]))
    negatives = sorted(negatives, key=lambda item: (-item[0], item[1]))
    return (
        list(dict.fromkeys(label for _, label in positives))[:3],
        list(dict.fromkeys(label for _, label in negatives))[:3],
    )


def primary_reason(row: dict[str, Any], negatives: list[str]) -> str:
    if row["explainability_quality"] == "PARTIAL":
        if pd.notna(row.get("final_score")):
            return "HIGH_SCORE_BUT_PARTIAL_COMPONENT_VISIBILITY"
        return "RANKED_WITH_LIMITED_COMPONENT_DATA"
    if "RISK_PENALTY_HIGH" in negatives and (
        row["momentum_contribution"] >= row["base_contribution"]
    ):
        return "HIGH_MOMENTUM_WITH_RISK_WARNING"
    if row["momentum_contribution"] >= row["base_contribution"]:
        return "MOMENTUM_LED_WITH_BASE_SUPPORT"
    return "BASE_LED_WITH_MOMENTUM_SUPPORT"


def mode_drivers(frame: pd.DataFrame, prefix: str) -> list[str]:
    values = []
    for column in (f"{prefix}_driver_1", f"{prefix}_driver_2", f"{prefix}_driver_3"):
        values.extend(value for value in frame[column].astype(str) if value and value != "nan")
    counts = Counter(values)
    return [name for name, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:3]]


def build_summary(ledger: pd.DataFrame) -> pd.DataFrame:
    eligible = ledger[ledger["eligible_flag"] == True].sort_values("rank")  # noqa: E712
    buckets = (
        ("TOP20", eligible.head(20)),
        ("TOP50", eligible.head(50)),
        ("ALL_ELIGIBLE", eligible),
    )
    rows = []
    for name, frame in buckets:
        positives = mode_drivers(frame, "positive")
        negatives = mode_drivers(frame, "negative")
        row = {
            "bucket": name,
            "row_count": len(frame),
            "avg_final_score": frame["final_score"].mean(),
            "avg_base_contribution": frame["base_contribution"].mean(),
            "avg_momentum_contribution": frame["momentum_contribution"].mean(),
            "avg_reconstruction_error": frame["reconstruction_error"].abs().mean(),
            "momentum_led_count": (
                frame["momentum_contribution"] >= frame["base_contribution"]
            ).sum(),
            "base_led_count": (
                frame["base_contribution"] > frame["momentum_contribution"]
            ).sum(),
            "partial_explainability_count": (
                frame["explainability_quality"] == "PARTIAL"
            ).sum(),
            "data_trust_warning_count": frame[
                ["negative_driver_1", "negative_driver_2", "negative_driver_3"]
            ].eq("DATA_TRUST_WARNING").any(axis=1).sum(),
            "risk_warning_count": frame[
                ["negative_driver_1", "negative_driver_2", "negative_driver_3"]
            ].eq("RISK_PENALTY_HIGH").any(axis=1).sum(),
        }
        row.update({f"top_positive_driver_{i + 1}": value for i, value in enumerate(positives)})
        row.update({f"top_negative_driver_{i + 1}": value for i, value in enumerate(negatives)})
        rows.append(row)
    return pd.DataFrame(rows).reindex(columns=SUMMARY_COLUMNS)


def write_blocked(
    root: Path, output_dir: Path, generated_at: str, reason: str
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=LEDGER_COLUMNS).to_csv(output_dir / LEDGER_NAME, index=False)
    pd.DataFrame(columns=SUMMARY_COLUMNS).to_csv(output_dir / SUMMARY_NAME, index=False)
    validation = {
        "stage": STAGE,
        "final_status": "BLOCKED_V21_067_R1_NO_VALID_D_RANKING_INPUT",
        "decision": "BLOCKED_REVIEW_INPUTS_OR_MUTATION_RISK",
        "generated_at_utc": generated_at,
        "source_ranking_path": "",
        "source_ranking_hash": "",
        "output_ledger_path": relative(root, output_dir / LEDGER_NAME),
        "output_summary_path": relative(root, output_dir / SUMMARY_NAME),
        "ranking_rows": 0, "eligible_rows": 0, "excluded_rows": 0,
        "ledger_rows": 0, "duplicate_ticker_count": 0,
        "missing_final_score_count": 0, "missing_rank_count": 0,
        "max_abs_reconstruction_error": "", "avg_abs_reconstruction_error": "",
        "reconstruction_pass_count": 0, "reconstruction_warn_count": 0,
        "partial_explainability_count": 0, "official_mutation": False,
        "protected_outputs_modified": False, "research_only": True,
        "pass_gate": False, "validation_warning": reason,
    }
    pd.DataFrame([validation]).to_csv(output_dir / VALIDATION_NAME, index=False)
    return validation


def run_stage(
    root: Path, ranking_override: Path | None = None, output_override: Path | None = None
) -> dict[str, Any]:
    root = root.resolve()
    output_dir = (
        output_override if output_override and output_override.is_absolute()
        else root / (output_override or OUT_REL)
    ).resolve()
    run_id, generated_at = utc_now()
    try:
        ranking_path, ranking = discover_ranking(root, ranking_override)
    except FileNotFoundError as exc:
        return write_blocked(root, output_dir, generated_at, str(exc))

    protected = protected_paths(root, ranking_path, output_dir)
    before = snapshot(protected)
    ranking_hash = sha256(ranking_path)
    components, component_sources = supplemental_components(
        root, ranking_path, set(ranking["ticker"].dropna().astype(str))
    )
    rows: list[dict[str, Any]] = []
    for _, source in ranking.iterrows():
        ticker = str(source["ticker"])
        base_weight = (
            source["base_weight"] if pd.notna(source["base_weight"]) else BASE_WEIGHT
        )
        momentum_weight = (
            source["momentum_weight"]
            if pd.notna(source["momentum_weight"]) else MOMENTUM_WEIGHT
        )
        base_contribution = source["base_contribution"]
        if pd.isna(base_contribution) and pd.notna(source["base_score"]):
            base_contribution = source["base_score"] * base_weight
        momentum_contribution = source["momentum_contribution"]
        if pd.isna(momentum_contribution) and pd.notna(source["momentum_score"]):
            momentum_contribution = source["momentum_score"] * momentum_weight
        reconstructed = (
            base_contribution + momentum_contribution
            if pd.notna(base_contribution) and pd.notna(momentum_contribution)
            else pd.NA
        )
        error = (
            reconstructed - source["final_score"]
            if pd.notna(reconstructed) and pd.notna(source["final_score"])
            else pd.NA
        )
        extra = components.get(ticker, {})
        missing = []
        available_families = 0
        available_subfactors = 0
        family_values: dict[str, Any] = {}
        for family in FAMILIES:
            score = extra.get(f"{family}_score_raw", pd.NA)
            weight = extra.get(f"{family}_weight", pd.NA)
            contribution = score * weight if pd.notna(score) and pd.notna(weight) else pd.NA
            family_values[f"{family}_score_raw"] = score
            family_values[f"{family}_contribution"] = contribution
            available_families += int(pd.notna(score))
            if pd.notna(score) and pd.isna(weight):
                missing.append(f"{family.upper()}_WEIGHT_UNAVAILABLE")
        subfactor_values = {
            column: extra.get(column, pd.NA) for column in SUBFACTOR_COLUMNS
        }
        available_subfactors = sum(pd.notna(value) for value in subfactor_values.values())
        if available_families < len(FAMILIES):
            missing.append("FAMILY_COMPONENTS_PARTIAL")
        if available_subfactors < len(SUBFACTORS):
            missing.append("TECHNICAL_SUBFACTORS_PARTIAL")
        quality = "COMPLETE" if not missing else "PARTIAL"
        row: dict[str, Any] = {
            "run_id": run_id, "generated_at_utc": generated_at,
            "source_ranking_path": relative(root, ranking_path),
            "source_ranking_hash": ranking_hash, "variant": VARIANT,
            "research_only": True, "official_mutation": False,
            "protected_outputs_modified": False, "ticker": ticker,
            "rank": source["rank"], "final_score": source["final_score"],
            "eligible_flag": bool(source["eligible"]),
            "exclusion_reason": source["exclusion"], "base_weight": base_weight,
            "momentum_weight": momentum_weight, "base_score_raw": source["base_score"],
            "momentum_score_raw": source["momentum_score"],
            "base_contribution": base_contribution,
            "momentum_contribution": momentum_contribution,
            "reconstructed_score": reconstructed, "reconstruction_error": error,
            "reconstruction_status": (
                "PASS" if pd.notna(error) and abs(float(error)) <= 1e-8
                else "WARN"
            ),
            "explainability_quality": quality,
            "missing_component_warning": "|".join(sorted(set(missing))),
            **family_values, **subfactor_values,
        }
        positives, negatives = driver_labels(row)
        for index in range(3):
            row[f"positive_driver_{index + 1}"] = (
                positives[index] if index < len(positives) else ""
            )
            row[f"negative_driver_{index + 1}"] = (
                negatives[index] if index < len(negatives) else ""
            )
        row["primary_ranking_reason"] = primary_reason(row, negatives)
        rows.append(row)

    ledger = pd.DataFrame(rows).reindex(columns=LEDGER_COLUMNS)
    summary = build_summary(ledger)
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(output_dir / LEDGER_NAME, index=False)
    summary.to_csv(output_dir / SUMMARY_NAME, index=False)

    after = snapshot(protected)
    changed = sorted(path for path, digest in before.items() if after.get(path) != digest)
    source_duplicates = int(ranking["ticker"].duplicated().sum())
    ledger_duplicates = int(ledger["ticker"].duplicated().sum())
    errors = ledger["reconstruction_error"].abs()
    ranked_mask = ledger["eligible_flag"] == True  # noqa: E712
    integrity = (
        len(ledger) == len(ranking)
        and ledger_duplicates <= source_duplicates
        and not changed
        and ledger.loc[ranked_mask, "final_score"].notna().all()
        and ledger.loc[ranked_mask, "rank"].notna().all()
        and ranking["research_only"].all()
    )
    partial_count = int((ledger["explainability_quality"] == "PARTIAL").sum())
    if not integrity:
        final_status = "BLOCKED_V21_067_R1_INTEGRITY_OR_MUTATION_RISK"
        decision = "BLOCKED_REVIEW_INPUTS_OR_MUTATION_RISK"
    elif partial_count:
        final_status = (
            "PARTIAL_PASS_V21_067_R1_FACTOR_EXPLAINABILITY_LEDGER_READY_"
            "WITH_COMPONENT_WARNINGS"
        )
        decision = (
            "FACTOR_EXPLAINABILITY_LEDGER_READY_WITH_COMPONENT_WARNINGS_"
            "RESEARCH_ONLY"
        )
    else:
        final_status = "PASS_V21_067_R1_FACTOR_EXPLAINABILITY_LEDGER_READY"
        decision = "FACTOR_EXPLAINABILITY_LEDGER_READY_RESEARCH_ONLY"
    validation = {
        "stage": STAGE, "final_status": final_status, "decision": decision,
        "generated_at_utc": generated_at,
        "source_ranking_path": relative(root, ranking_path),
        "source_ranking_hash": ranking_hash,
        "output_ledger_path": relative(root, output_dir / LEDGER_NAME),
        "output_summary_path": relative(root, output_dir / SUMMARY_NAME),
        "ranking_rows": len(ranking),
        "eligible_rows": int(ranking["eligible"].sum()),
        "excluded_rows": int((~ranking["eligible"]).sum()),
        "ledger_rows": len(ledger), "duplicate_ticker_count": ledger_duplicates,
        "missing_final_score_count": int(
            ledger.loc[ranked_mask, "final_score"].isna().sum()
        ),
        "missing_rank_count": int(ledger.loc[ranked_mask, "rank"].isna().sum()),
        "max_abs_reconstruction_error": errors.max(),
        "avg_abs_reconstruction_error": errors.mean(),
        "reconstruction_pass_count": int(
            (ledger["reconstruction_status"] == "PASS").sum()
        ),
        "reconstruction_warn_count": int(
            (ledger["reconstruction_status"] == "WARN").sum()
        ),
        "partial_explainability_count": partial_count,
        "official_mutation": False,
        "protected_outputs_modified": bool(changed),
        "research_only": True, "pass_gate": bool(integrity),
        "component_sources": json.dumps(component_sources, sort_keys=True),
        "protected_modified_paths": "|".join(changed),
    }
    pd.DataFrame([validation]).to_csv(output_dir / VALIDATION_NAME, index=False)
    return validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--ranking-path", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    result = run_stage(args.root, args.ranking_path, args.output_dir)
    print(f"FINAL_STATUS={result['final_status']}")
    print(f"DECISION={result['decision']}")
    print(f"SOURCE_RANKING_PATH={result['source_ranking_path']}")
    print(f"SOURCE_RANKING_HASH={result['source_ranking_hash']}")
    print(f"VALIDATION_SUMMARY={(args.output_dir or OUT_REL) / VALIDATION_NAME}")
    return 1 if str(result["final_status"]).startswith("BLOCKED_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
