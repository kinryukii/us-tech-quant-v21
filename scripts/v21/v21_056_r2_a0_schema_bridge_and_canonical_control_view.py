#!/usr/bin/env python
"""Build a non-mutating canonical schema view over the frozen V21 A0 ledger."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


STAGE_ID = "V21.056-R2"
FROZEN_VERSION_ID = "A0_CURRENT_TESTING_LOCKED"
PASS_STATUS = "PASS_V21_056_R2_A0_CANONICAL_CONTROL_VIEW_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_056_R2_A0_CANONICAL_VIEW_READY_WITH_SCHEMA_WARN"
BLOCKED_STATUS = "BLOCKED_V21_056_R2_A0_CANONICAL_VIEW_NOT_CREATED"
FAIL_STATUS = "FAIL_V21_056_R2_FORBIDDEN_MUTATION_DETECTED"

PASS_DECISION = "A0_CANONICAL_CONTROL_READY_FOR_V21_057_UNIFIED_POOL"
PARTIAL_DECISION = "A0_CANONICAL_CONTROL_USABLE_WITH_LIMITED_RANK_OR_MATURITY_COMPARISON"
BLOCKED_DECISION = "FIX_A0_CANONICAL_VIEW_BEFORE_ABCD_EXPERIMENTS"
FAIL_DECISION = "STOP_AND_RESTORE_FORBIDDEN_MUTATION"

OUTPUT_DIR_REL = Path("outputs/v21/experiments/version_control")
INPUT_SNAPSHOT_NAME = "V21_056_R1_A0_LEDGER_SNAPSHOT.csv"
INPUT_MANIFEST_NAME = "V21_056_R1_A0_CURRENT_TESTING_LOCKED_MANIFEST.json"
VIEW_NAME = "V21_056_R2_A0_CANONICAL_CONTROL_VIEW.csv"
GAP_AUDIT_NAME = "V21_056_R2_A0_SCHEMA_GAP_AUDIT.csv"
JOIN_AUDIT_NAME = "V21_056_R2_A0_JOIN_CANDIDATE_AUDIT.csv"
MANIFEST_NAME = "V21_056_R2_A0_CANONICAL_CONTROL_MANIFEST.json"
SUMMARY_NAME = "V21_056_R2_SUMMARY.json"

VIEW_FIELDS = [
    "observation_id", "as_of_date", "version_id", "variant_id", "ticker",
    "rank", "rank_available", "rank_source", "score", "score_available",
    "score_source", "forward_window", "scheduled_maturity_date",
    "scheduled_maturity_date_available", "scheduled_maturity_date_source",
    "maturity_status", "realized_forward_return", "canonical_bridge_status",
    "schema_gap_flags", "source_snapshot_path", "source_row_hash",
]
GAP_FIELDS = [
    "field_name", "exists_in_snapshot", "missing_count", "non_null_count",
    "fill_method", "filled_count", "still_missing_count", "notes",
]
JOIN_FIELDS = [
    "candidate_file", "exists", "row_count", "available_join_keys",
    "rank_field_found", "score_field_found",
    "scheduled_maturity_date_field_found", "usable_for_rank_join",
    "usable_for_score_join", "usable_for_maturity_date_join", "rejection_reason",
]
RANK_ALIASES = ("rank", "technical_only_rank", "within_regime_alpha_only_rank", "global_alpha_only_rank", "bucket_rank")
SCORE_ALIASES = ("score", "composite_candidate_score", "alpha_only_score", "technical_only_score", "prototype_score")
MATURITY_ALIASES = ("scheduled_maturity_date", "maturity_date", "due_date")
WINDOW_ALIASES = ("forward_window", "forward_return_window")
DATE_ALIASES = ("as_of_date", "observation_as_of_date", "latest_price_date")
VARIANT_ALIASES = ("variant_id", "lane_id", "research_stream")


def load_maturity_helper() -> object:
    path = Path(__file__).with_name("v21_044_r7_technical_only_current_daily_observation_ledger_append.py")
    spec = importlib.util.spec_from_file_location("v21_044_r7_maturity_helper", path)
    if not spec or not spec.loader:
        raise RuntimeError("Existing V21 maturity helper could not be loaded.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def row_hash(row: dict[str, str], fields: list[str]) -> str:
    payload = json.dumps(
        {field: str(row.get(field, "") or "") for field in fields},
        ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.is_file() or path.stat().st_size == 0:
        return [], []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            return [dict(row) for row in reader], list(reader.fieldnames or [])
    except (OSError, UnicodeError, csv.Error):
        return [], []


def read_header(path: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(next(csv.reader(handle), []))
    except (OSError, UnicodeError, csv.Error):
        return []


def write_csv(path: Path, rows: Iterable[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                field: (
                    "" if row.get(field) is None
                    else "TRUE" if row.get(field) is True
                    else "FALSE" if row.get(field) is False
                    else row.get(field, "")
                )
                for field in fields
            })


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def first_field(fields: Iterable[str], aliases: Iterable[str]) -> str:
    lookup = {field.lower(): field for field in fields}
    return next((lookup[alias] for alias in aliases if alias in lookup), "")


def clean(value: object) -> str:
    return str(value or "").strip()


def normalize_window(value: object) -> str:
    text = clean(value).upper().replace(" ", "")
    match = re.fullmatch(r"(\d+)(?:D|DAY|DAYS)?", text)
    return f"{int(match.group(1))}D" if match else text


def finite_number(value: object) -> str:
    text = clean(value)
    try:
        return text if text and math.isfinite(float(text)) else ""
    except ValueError:
        return ""


def protected_snapshot(root: Path) -> dict[str, dict[str, str]]:
    groups = {
        "r1_inputs": {}, "official_ranking": {}, "official_weights": {},
        "real_book": {}, "broker": {},
    }
    output_dir = root / OUTPUT_DIR_REL
    for name in (INPUT_SNAPSHOT_NAME, INPUT_MANIFEST_NAME):
        path = output_dir / name
        if path.is_file():
            groups["r1_inputs"][rel(root, path)] = sha256(path)
    for base in (root / "outputs", root / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or output_dir in path.parents:
                continue
            text = rel(root, path).lower().replace("-", "_").replace(" ", "_")
            group = ""
            if "broker" in text:
                group = "broker"
            elif "real_book" in text or "realbook" in text:
                group = "real_book"
            elif "official" in text and ("weight" in text or "allocation" in text):
                group = "official_weights"
            elif "official" in text and ("rank" in text or "recommend" in text):
                group = "official_ranking"
            if group:
                groups[group][rel(root, path)] = sha256(path)
    return groups


def changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))


def candidate_paths(root: Path, snapshot_rows: list[dict[str, str]]) -> list[Path]:
    result: set[Path] = set()
    likely = [
        root / "outputs/v18/candidates/V18_CURRENT_RANKED_CANDIDATES.csv",
        root / "outputs/v21/shadow_observation/V21_029_R1_CURRENT_DAILY_SHADOW_OBSERVATION_LEDGER.csv",
        root / "outputs/v21/shadow_observation/V21_029_OBSERVATION_LEDGER.csv",
        root / "outputs/v21/shadow_observation/V21_029_FORWARD_OBSERVATION_SCHEDULE.csv",
        root / "outputs/v21/shadow_observation/V21_029_WITHIN_REGIME_ALPHA_ONLY_RANKS.csv",
        root / "outputs/v21/ledger/V21_044_R7_TECHNICAL_ONLY_OBSERVATION_LEDGER.csv",
        root / "outputs/v21/ledger/V21_044_R8_R1_TECHNICAL_ONLY_OBSERVATION_LEDGER_REFRESHED_WITH_REPAIR.csv",
    ]
    result.update(likely)
    companion = root / "outputs/v21/shadow_observation/V21_029_R1_CURRENT_DAILY_SHADOW_OBSERVATION_LEDGER.csv"
    rows, _ = read_csv(companion)
    for row in rows:
        source = clean(row.get("source_artifact"))
        if source:
            result.add(root / source)
    for row in snapshot_rows:
        source = clean(row.get("source_artifact"))
        if source:
            result.add(root / source)
    return sorted(result, key=lambda path: path.as_posix().lower())


def build_candidate(
    root: Path, path: Path, snapshot_dates: set[str],
) -> tuple[dict[str, object], dict[str, dict[tuple[str, ...], tuple[str, bool]]]]:
    fields = read_header(path)
    date_field = first_field(fields, DATE_ALIASES)
    ticker_field = first_field(fields, ("ticker", "symbol"))
    window_field = first_field(fields, WINDOW_ALIASES)
    observation_field = first_field(fields, ("observation_id",))
    context_field = first_field(fields, ("context_key", "context_label", "context_combination"))
    lane_field = first_field(fields, ("lane_id", "variant_id", "research_stream"))
    rank_field = first_field(fields, RANK_ALIASES)
    score_field = first_field(fields, SCORE_ALIASES)
    maturity_field = first_field(fields, MATURITY_ALIASES)
    keys: list[str] = []
    if observation_field:
        keys.append("observation_id")
    if date_field and ticker_field and window_field:
        keys.append("as_of_date+ticker+forward_window")
    if date_field and ticker_field and context_field and lane_field and window_field:
        keys.append("as_of_date+ticker+context+lane+forward_window")
    if date_field and ticker_field:
        keys.append("as_of_date+ticker")
    exists = path.is_file()
    rows: list[dict[str, str]] = []
    if exists:
        rows, _ = read_csv(path)

    maps: dict[str, dict[tuple[str, ...], tuple[str, bool]]] = {
        "rank": {}, "score": {}, "maturity": {},
    }
    raw: dict[str, dict[tuple[str, ...], set[str]]] = {
        "rank": defaultdict(set), "score": defaultdict(set), "maturity": defaultdict(set),
    }
    source_kind = (
        "JOINED_FROM_SOURCE_OBSERVATION_LEDGER"
        if "observation" in path.name.lower() or "ledger" in path.name.lower()
        else "JOINED_FROM_SOURCE_RANKING"
    )
    for row in rows:
        day = clean(row.get(date_field))
        ticker = clean(row.get(ticker_field)).upper()
        window = normalize_window(row.get(window_field))
        oid = clean(row.get(observation_field))
        context = clean(row.get(context_field))
        lane = clean(row.get(lane_field))
        row_keys: list[tuple[str, ...]] = []
        if oid:
            row_keys.append(("observation_id", oid))
        if day and ticker and window:
            row_keys.append(("date_ticker_window", day, ticker, window))
        if day and ticker and context and lane and window:
            row_keys.append(("date_ticker_context_lane_window", day, ticker, context, lane, window))
        if day and ticker:
            row_keys.append(("date_ticker", day, ticker))
        for key in row_keys:
            if rank_field and finite_number(row.get(rank_field)):
                raw["rank"][key].add(finite_number(row.get(rank_field)))
            if score_field and finite_number(row.get(score_field)):
                raw["score"][key].add(finite_number(row.get(score_field)))
            if maturity_field and clean(row.get(maturity_field)):
                raw["maturity"][key].add(clean(row.get(maturity_field)))
    for kind in raw:
        maps[kind] = {
            key: (next(iter(vals)) if len(vals) == 1 else "", len(vals) > 1)
            for key, vals in raw[kind].items()
        }
    maps["_meta"] = {  # type: ignore[assignment]
        "rank_source": {("value",): (source_kind, False)},
        "score_source": {("value",): (rel(root, path) if exists else "", False)},
        "maturity_source": {("value",): (rel(root, path) if exists else "", False)},
    }
    relevant_date = not snapshot_dates or any(
        clean(row.get(date_field)) in snapshot_dates for row in rows
    )
    rejection: list[str] = []
    if not exists:
        rejection.append("FILE_NOT_FOUND")
    if not ticker_field:
        rejection.append("TICKER_FIELD_NOT_FOUND")
    if not keys:
        rejection.append("NO_ACCEPTABLE_JOIN_KEY")
    if rows and not relevant_date:
        rejection.append("NO_ROWS_FOR_FROZEN_AS_OF_DATE")
    if not (rank_field or score_field or maturity_field):
        rejection.append("NO_BRIDGE_FIELDS")
    usable_base = exists and bool(keys) and bool(rows) and relevant_date
    audit = {
        "candidate_file": rel(root, path) if path.is_absolute() and path.exists() else path.as_posix(),
        "exists": exists,
        "row_count": len(rows),
        "available_join_keys": "|".join(keys),
        "rank_field_found": rank_field,
        "score_field_found": score_field,
        "scheduled_maturity_date_field_found": maturity_field,
        "usable_for_rank_join": usable_base and bool(rank_field),
        "usable_for_score_join": usable_base and bool(score_field),
        "usable_for_maturity_date_join": usable_base and bool(maturity_field),
        "rejection_reason": "|".join(rejection),
    }
    return audit, maps


def lookup_keys(row: dict[str, str]) -> list[tuple[str, ...]]:
    oid = clean(row.get("observation_id"))
    day = clean(row.get("as_of_date"))
    ticker = clean(row.get("ticker")).upper()
    window = normalize_window(row.get("forward_return_window") or row.get("forward_window"))
    context = clean(row.get("context_key") or row.get("context_label") or row.get("context_combination"))
    lane = clean(row.get("lane_id") or row.get("variant_id") or row.get("research_stream"))
    keys: list[tuple[str, ...]] = []
    if oid:
        keys.append(("observation_id", oid))
    if day and ticker and context and lane and window:
        keys.append(("date_ticker_context_lane_window", day, ticker, context, lane, window))
    if day and ticker and window:
        keys.append(("date_ticker_window", day, ticker, window))
    if day and ticker:
        keys.append(("date_ticker", day, ticker))
    return keys


def joined_value(
    row: dict[str, str], kind: str,
    candidates: list[tuple[dict[str, object], dict[str, dict[tuple[str, ...], tuple[str, bool]]]]],
) -> tuple[str, str, bool]:
    ambiguous = False
    for audit, maps in candidates:
        usable = bool(audit[f"usable_for_{'maturity_date' if kind == 'maturity' else kind}_join"])
        if not usable:
            continue
        for key in lookup_keys(row):
            match = maps[kind].get(key)
            if not match:
                continue
            value, is_ambiguous = match
            if is_ambiguous:
                ambiguous = True
                continue
            if value:
                if kind == "rank":
                    source = maps["_meta"]["rank_source"][("value",)][0]
                elif kind == "score":
                    source = maps["_meta"]["score_source"][("value",)][0]
                else:
                    source = "EXISTING_SOURCE_FIELD"
                return value, source, ambiguous
    return "", "", ambiguous


def run_stage(root: Path) -> dict[str, object]:
    root = root.resolve()
    out = root / OUTPUT_DIR_REL
    out.mkdir(parents=True, exist_ok=True)
    snapshot_path = out / INPUT_SNAPSHOT_NAME
    r1_manifest_path = out / INPUT_MANIFEST_NAME
    view_path = out / VIEW_NAME
    before = protected_snapshot(root)

    input_rows, input_fields = read_csv(snapshot_path)
    valid_inputs = bool(input_rows and r1_manifest_path.is_file())
    r1_manifest: dict[str, object] = {}
    if r1_manifest_path.is_file():
        try:
            r1_manifest = json.loads(r1_manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            valid_inputs = False
    if r1_manifest.get("frozen_version_id") != FROZEN_VERSION_ID:
        valid_inputs = False
    expected_hash = clean(r1_manifest.get("snapshot_ledger_sha256"))
    if expected_hash and snapshot_path.is_file() and sha256(snapshot_path) != expected_hash:
        valid_inputs = False

    snapshot_dates = {clean(row.get("as_of_date")) for row in input_rows if clean(row.get("as_of_date"))}
    candidate_data = [build_candidate(root, path, snapshot_dates) for path in candidate_paths(root, input_rows)]
    write_csv(out / JOIN_AUDIT_NAME, (audit for audit, _ in candidate_data), JOIN_FIELDS)

    helper = load_maturity_helper()
    canonical_rows: list[dict[str, object]] = []
    if valid_inputs:
        for source in input_rows:
            oid = clean(source.get("observation_id"))
            day = clean(source.get("as_of_date"))
            ticker = clean(source.get("ticker")).upper()
            window = normalize_window(source.get("forward_return_window") or source.get("forward_window"))

            rank = finite_number(source.get("rank"))
            rank_source = "JOINED_FROM_SOURCE_OBSERVATION_LEDGER" if rank else ""
            rank_ambiguous = False
            if not rank:
                rank, rank_source, rank_ambiguous = joined_value(source, "rank", candidate_data)
            if not rank:
                rank_source = "AMBIGUOUS_JOIN_NOT_DERIVED" if rank_ambiguous else "MISSING_NOT_DERIVED"

            score_field = first_field(input_fields, SCORE_ALIASES)
            score = finite_number(source.get(score_field))
            score_source = rel(root, snapshot_path) if score else ""
            score_ambiguous = False
            if not score:
                score, score_source, score_ambiguous = joined_value(source, "score", candidate_data)
            if not score:
                score_source = "AMBIGUOUS_JOIN_NOT_DERIVED" if score_ambiguous else "MISSING_NOT_DERIVED"

            maturity_field = first_field(input_fields, MATURITY_ALIASES)
            maturity = clean(source.get(maturity_field))
            maturity_source = "EXISTING_SOURCE_FIELD" if maturity else ""
            maturity_ambiguous = False
            if not maturity:
                maturity, maturity_source, maturity_ambiguous = joined_value(source, "maturity", candidate_data)
            if not maturity and day and window:
                parsed_day = helper.parse_date(day)
                match = re.fullmatch(r"(\d+)D", window)
                if parsed_day and match:
                    maturity, _ = helper.maturity_date(parsed_day, [], int(match.group(1)))
                    maturity_source = "DERIVED_FROM_EXISTING_V21_TRADING_DAY_LOGIC"
            if not maturity:
                maturity_source = "AMBIGUOUS_NOT_DERIVED" if maturity_ambiguous else "MISSING_NOT_DERIVED"

            flags: list[str] = []
            if not rank:
                flags.append("MISSING_RANK")
            if not score:
                flags.append("MISSING_SCORE")
            if not maturity:
                flags.append("MISSING_SCHEDULED_MATURITY_DATE")
            if not window:
                flags.append("MISSING_FORWARD_WINDOW")
            if not ticker:
                flags.append("MISSING_TICKER")
            if not day:
                flags.append("MISSING_AS_OF_DATE")
            if rank_ambiguous and not rank:
                flags.append("AMBIGUOUS_RANK_JOIN")
            if maturity_ambiguous and not maturity:
                flags.append("AMBIGUOUS_MATURITY_DATE_JOIN")
            if not flags:
                flags.append("NO_SCHEMA_GAP")
            blocked = not oid or not ticker or not day
            complete = all((oid, ticker, day, window, rank, maturity))
            status = "BLOCKED_BRIDGE" if blocked else "COMPLETE_BRIDGE" if complete else "PARTIAL_BRIDGE"
            canonical_rows.append({
                "observation_id": oid,
                "as_of_date": day,
                "version_id": FROZEN_VERSION_ID,
                "variant_id": FROZEN_VERSION_ID,
                "ticker": ticker,
                "rank": rank,
                "rank_available": bool(rank),
                "rank_source": rank_source,
                "score": score,
                "score_available": bool(score),
                "score_source": score_source,
                "forward_window": window,
                "scheduled_maturity_date": maturity,
                "scheduled_maturity_date_available": bool(maturity),
                "scheduled_maturity_date_source": maturity_source,
                "maturity_status": clean(source.get("maturity_status") or source.get("observation_status")),
                "realized_forward_return": clean(source.get("realized_forward_return")),
                "canonical_bridge_status": status,
                "schema_gap_flags": "|".join(flags),
                "source_snapshot_path": rel(root, snapshot_path),
                "source_row_hash": row_hash(source, input_fields),
            })

    if canonical_rows:
        write_csv(view_path, canonical_rows, VIEW_FIELDS)
    elif view_path.exists():
        view_path.unlink()

    input_count = len(input_rows)
    canonical_count = len(canonical_rows)
    ids = [clean(row.get("observation_id")) for row in canonical_rows]
    id_counts = Counter(value for value in ids if value)
    duplicate_count = sum(count - 1 for count in id_counts.values() if count > 1)
    complete_count = sum(row["canonical_bridge_status"] == "COMPLETE_BRIDGE" for row in canonical_rows)
    partial_count = sum(row["canonical_bridge_status"] == "PARTIAL_BRIDGE" for row in canonical_rows)
    blocked_count = sum(row["canonical_bridge_status"] == "BLOCKED_BRIDGE" for row in canonical_rows)
    rank_count = sum(bool(row["rank_available"]) for row in canonical_rows)
    score_count = sum(bool(row["score_available"]) for row in canonical_rows)
    maturity_count = sum(bool(row["scheduled_maturity_date_available"]) for row in canonical_rows)

    field_specs = [
        ("observation_id", "observation_id", "PRESERVED_FROM_SNAPSHOT"),
        ("as_of_date", "as_of_date", "PRESERVED_FROM_SNAPSHOT"),
        ("ticker", "ticker", "PRESERVED_FROM_SNAPSHOT"),
        ("forward_window", first_field(input_fields, WINDOW_ALIASES), "NORMALIZED_FROM_SNAPSHOT"),
        ("version_id", first_field(input_fields, ("version_id",)), "CONSTANT_A0_CURRENT_TESTING_LOCKED"),
        ("variant_id", first_field(input_fields, ("variant_id",)), "CONSTANT_A0_CURRENT_TESTING_LOCKED"),
        ("rank", first_field(input_fields, RANK_ALIASES), "UNAMBIGUOUS_READ_ONLY_JOIN"),
        ("score", first_field(input_fields, SCORE_ALIASES), "PRESERVE_OR_UNAMBIGUOUS_READ_ONLY_JOIN"),
        ("scheduled_maturity_date", first_field(input_fields, MATURITY_ALIASES), "SOURCE_JOIN_OR_EXISTING_V21_TRADING_DAY_LOGIC"),
    ]
    gap_rows = []
    for canonical_field, source_field, method in field_specs:
        before_non_null = sum(bool(clean(row.get(source_field))) for row in input_rows) if source_field else 0
        after_non_null = sum(bool(clean(row.get(canonical_field))) for row in canonical_rows)
        gap_rows.append({
            "field_name": canonical_field,
            "exists_in_snapshot": bool(source_field),
            "missing_count": input_count - before_non_null,
            "non_null_count": before_non_null,
            "fill_method": method,
            "filled_count": max(0, after_non_null - before_non_null),
            "still_missing_count": canonical_count - after_non_null,
            "notes": "No historical rank or score was recomputed.",
        })
    write_csv(out / GAP_AUDIT_NAME, gap_rows, GAP_FIELDS)

    after = protected_snapshot(root)
    r1_changes = changed(before["r1_inputs"], after["r1_inputs"])
    official_changes = changed(before["official_ranking"], after["official_ranking"]) + changed(before["official_weights"], after["official_weights"])
    real_book_changes = changed(before["real_book"], after["real_book"])
    broker_changes = changed(before["broker"], after["broker"])
    official_mutation = bool(official_changes or r1_changes)
    real_book_mutation = bool(real_book_changes)
    broker_mutation = bool(broker_changes)
    forbidden = official_mutation or real_book_mutation or broker_mutation
    created = view_path.is_file() and canonical_count == input_count and input_count > 0
    ready = created and blocked_count == 0 and not forbidden
    warnings: list[str] = []
    if rank_count < canonical_count:
        warnings.append("RANK_PARTIALLY_MISSING")
    if maturity_count < canonical_count:
        warnings.append("SCHEDULED_MATURITY_DATE_PARTIALLY_MISSING")
    if score_count < canonical_count:
        warnings.append("SCORE_PARTIALLY_MISSING")

    if forbidden:
        final_status, decision = FAIL_STATUS, FAIL_DECISION
    elif not created:
        final_status, decision = BLOCKED_STATUS, BLOCKED_DECISION
    elif blocked_count:
        final_status, decision = BLOCKED_STATUS, BLOCKED_DECISION
    elif rank_count < canonical_count or maturity_count < canonical_count:
        final_status, decision = PARTIAL_STATUS, PARTIAL_DECISION
    else:
        final_status, decision = PASS_STATUS, PASS_DECISION

    manifest = {
        "stage_id": STAGE_ID,
        "frozen_version_id": FROZEN_VERSION_ID,
        "input_snapshot_path": rel(root, snapshot_path),
        "canonical_view_path": rel(root, view_path) if view_path.is_file() else None,
        "input_row_count": input_count,
        "canonical_row_count": canonical_count,
        "unique_observation_id_count": len(id_counts),
        "duplicate_observation_id_count": duplicate_count,
        "version_id_filled_count": sum(row["version_id"] == FROZEN_VERSION_ID for row in canonical_rows),
        "variant_id_filled_count": sum(row["variant_id"] == FROZEN_VERSION_ID for row in canonical_rows),
        "rank_available_count": rank_count,
        "rank_missing_count": canonical_count - rank_count,
        "scheduled_maturity_date_available_count": maturity_count,
        "scheduled_maturity_date_missing_count": canonical_count - maturity_count,
        "score_available_count": score_count,
        "score_missing_count": canonical_count - score_count,
        "complete_bridge_count": complete_count,
        "partial_bridge_count": partial_count,
        "blocked_bridge_count": blocked_count,
        "official_mutation_detected": official_mutation,
        "real_book_mutation_detected": real_book_mutation,
        "broker_mutation_detected": broker_mutation,
        "research_only": True,
        "ready_for_abcd_experiment": ready,
        "remaining_schema_warnings": warnings,
        "input_snapshot_sha256": sha256(snapshot_path) if snapshot_path.is_file() else None,
        "canonical_view_sha256": sha256(view_path) if view_path.is_file() else None,
        "created_at_utc": now_utc(),
    }
    write_json(out / MANIFEST_NAME, manifest)
    summary = {
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "stage_id": STAGE_ID,
        "frozen_version_id": FROZEN_VERSION_ID,
        "input_snapshot_path": rel(root, snapshot_path),
        "canonical_view_path": rel(root, view_path) if view_path.is_file() else None,
        "input_row_count": input_count,
        "canonical_row_count": canonical_count,
        "complete_bridge_count": complete_count,
        "partial_bridge_count": partial_count,
        "blocked_bridge_count": blocked_count,
        "rank_available_count": rank_count,
        "rank_missing_count": canonical_count - rank_count,
        "scheduled_maturity_date_available_count": maturity_count,
        "scheduled_maturity_date_missing_count": canonical_count - maturity_count,
        "official_mutation_detected": official_mutation,
        "real_book_mutation_detected": real_book_mutation,
        "broker_mutation_detected": broker_mutation,
        "research_only": True,
        "ready_for_abcd_experiment": ready,
        "next_recommended_stage": (
            "V21.057_UNIFIED_POOL" if final_status == PASS_STATUS
            else "V21.057_UNIFIED_POOL_WITH_LIMITED_RANK_OR_MATURITY_COMPARISON" if final_status == PARTIAL_STATUS
            else "REPAIR_A0_CANONICAL_CONTROL_VIEW_INPUTS" if final_status == BLOCKED_STATUS
            else "RESTORE_FORBIDDEN_MUTATION_AND_RERUN_V21_056_R2"
        ),
    }
    write_json(out / SUMMARY_NAME, summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    summary = run_stage(args.root)
    print(json.dumps(summary, indent=2))
    return 1 if summary["FINAL_STATUS"] in {BLOCKED_STATUS, FAIL_STATUS} else 0


if __name__ == "__main__":
    raise SystemExit(main())
