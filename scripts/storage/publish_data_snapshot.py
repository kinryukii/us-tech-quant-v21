"""Prepare immutable CSV exports; pointer publication requires a legacy scope.

Default preparation does not inspect or modify the legacy current pointer. The
catalog remains the development interface. Explicit publication accepts only
the existing V21.231 expected-universe manifest at the current pointer location,
with matching declared count and complete target-date coverage in both modes.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import tempfile
from datetime import date
from pathlib import Path

from scripts.storage.storage_r2a import DataStore
from scripts.storage.build_data_catalog import sha256, utc_now


POINTER_REL = "current/V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD/canonical_snapshot_pointer.json"
FIELDS = ["ticker", "moomoo_symbol", "market", "date", "open", "high", "low", "close", "volume",
          "turnover", "adjustment", "source", "source_policy", "snapshot_id", "fetched_at_utc"]


def json_bytes(payload):
    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def atomic_bytes(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
    try:
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_json(path, payload):
    atomic_bytes(path, json_bytes(payload))


def legacy_scope(store, current):
    """Only reuse the scope authority already read by the V21.231 consumers."""
    if not current.is_file():
        raise ValueError("LEGACY_SCOPE_CONTRACT_MISSING: existing current pointer required")
    original = current.read_bytes()
    pointer = json.loads(original)
    if pointer.get("policy_version") != "V21.231" or pointer.get("source_policy") != "MOOMOO_ONLY":
        raise ValueError("LEGACY_SCOPE_CONTRACT_UNSUPPORTED")
    scope_path = store._check_data_path(current.parent / "abcde_expected_universe.csv")
    scope_bytes = scope_path.read_bytes()
    reader = csv.DictReader(io.StringIO(scope_bytes.decode("utf-8-sig")))
    if "ticker" not in (reader.fieldnames or []):
        raise ValueError("LEGACY_SCOPE_CONTRACT_INVALID: ticker column required")
    rows = list(reader)
    symbols = [store._ticker(row.get("ticker", "")) for row in rows]
    if any(row.get("ticker") != symbol for row, symbol in zip(rows, symbols)):
        raise ValueError("LEGACY_SCOPE_CONTRACT_INVALID: symbols must already be canonical")
    if not symbols or len(symbols) != len(set(symbols)):
        raise ValueError("LEGACY_SCOPE_CONTRACT_INVALID: empty or duplicate symbols")
    if type(pointer.get("expected_universe_count")) is not int or pointer["expected_universe_count"] != len(symbols):
        raise ValueError("LEGACY_SCOPE_CONTRACT_AMBIGUOUS: pointer count differs from existing manifest")
    return set(symbols), original, scope_path, scope_bytes


def backup_bytes(report_root, name, original):
    digest = hashlib.sha256(original).hexdigest()
    path = report_root / f"prior_{name}_{digest[:20]}.backup"
    if path.exists():
        if path.read_bytes() != original:
            raise ValueError("Prior pointer backup content mismatch")
    else:
        with path.open("xb") as handle:
            handle.write(original)
    return path


def commit_pointer(current, pointer, original, scope_path, scope_bytes, report_root, modes):
    mirror = current.with_suffix(".csv")
    mirror_original = mirror.read_bytes() if mirror.exists() else None
    backup = backup_bytes(report_root, "canonical_pointer_json", original)
    mirror_backup = backup_bytes(report_root, "canonical_pointer_csv", mirror_original) if mirror_original is not None else None
    csv_text = io.StringIO(newline="")
    writer = csv.writer(csv_text, lineterminator="\n")
    writer.writerow(["key", "value"])
    writer.writerows(pointer.items())
    mirror_new, pointer_new = csv_text.getvalue().encode("utf-8"), json_bytes(pointer)
    for item in modes.values():
        if sha256(item["path"]) != item["sha256"]:
            raise ValueError("Export changed before publication")
    # Other producers do not share a lock. Refuse any observed intervening
    # change; this check plus atomic replacement is not a global writer lock.
    if current.read_bytes() != original or scope_path.read_bytes() != scope_bytes:
        raise ValueError("LEGACY_POINTER_OR_SCOPE_CHANGED_DURING_PREPARATION")
    if (mirror.read_bytes() if mirror.exists() else None) != mirror_original:
        raise ValueError("LEGACY_CSV_POINTER_CHANGED_DURING_PREPARATION")
    try:
        atomic_bytes(mirror, mirror_new)
        if current.read_bytes() != original or scope_path.read_bytes() != scope_bytes:
            raise ValueError("LEGACY_POINTER_OR_SCOPE_CHANGED_BEFORE_COMMIT")
        atomic_bytes(current, pointer_new)
        reread = json.loads(current.read_bytes())
        if reread != pointer:
            raise ValueError("Pointer read-back mismatch")
        for adjustment, item in modes.items():
            if sha256(reread[f"canonical_{adjustment}_path"]) != item["sha256"]:
                raise ValueError("Post-publication hash failed")
    except BaseException:
        # Restore only bytes still owned by this attempt; never overwrite a
        # different writer's observed update during failure handling.
        if current.exists() and current.read_bytes() == pointer_new:
            atomic_bytes(current, original)
        if mirror.exists() and mirror.read_bytes() == mirror_new:
            if mirror_original is None:
                mirror.unlink()
            else:
                atomic_bytes(mirror, mirror_original)
        raise
    return backup, mirror_backup


def publish(store, target_date, report_root, *, publish_pointer=False):
    if date.fromisoformat(target_date).isoformat() != target_date:
        raise ValueError("target date must use YYYY-MM-DD")
    report_root = store._check_data_path(Path(report_root), must_exist=False)
    current = store.paths.daily_root / POINTER_REL
    original = scope_path = scope_bytes = None
    scope = None
    if publish_pointer:
        scope, original, scope_path, scope_bytes = legacy_scope(store, current)
    raw = store._catalog_rows("prices_daily", adjustment="raw")
    qfq = store._catalog_rows("prices_daily", adjustment="qfq")
    by_mode = {"raw": {row["ticker"]: row for row in raw}, "qfq": {row["ticker"]: row for row in qfq}}
    paired = set(by_mode["raw"]) & set(by_mode["qfq"])
    if scope is not None and not scope <= paired:
        raise ValueError("LEGACY_SCOPE_MISSING_PRICE_LEGS:" + ",".join(sorted(scope - paired)))
    common = sorted(scope if scope is not None else paired)
    if not common:
        raise ValueError("No symbol has both raw and QFQ histories")
    selection_scope = "EXISTING_LEGACY_EXPECTED_UNIVERSE" if scope is not None else "CATALOG_PAIRED_PROVIDER_SYMBOLS_NOT_STRATEGY_UNIVERSE"
    identity = {"export_schema_version": 2, "target_date": target_date, "selection_scope": selection_scope,
                "scope_sha256": hashlib.sha256(scope_bytes).hexdigest() if scope_bytes is not None else None,
                "files": [[a, ticker, by_mode[a][ticker]["source_sha256"]] for a in ["raw", "qfq"] for ticker in common]}
    stamp = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
    snapshot_id = f"data_layer_{target_date.replace('-', '')}_{stamp}"
    root = store._check_data_path(store.paths.data_root / "canonical/moomoo_ohlcv" / f"snapshot_id={snapshot_id}", must_exist=False)
    root.mkdir(parents=True, exist_ok=True)
    modes, targets, latest, actual_sets, source_labels = {}, {}, {}, {}, set()
    for adjustment in ["raw", "qfq"]:
        path = root / f"canonical_moomoo_ohlcv_daily_{adjustment}.csv"
        count, target_set, exported_set, last = 0, set(), set(), ""
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=root,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            try:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                writer.writeheader()
                for ticker in common:
                    record = by_mode[adjustment][ticker]
                    if not Path(record["path"]).is_absolute():
                        raise ValueError("Catalog export paths must be absolute")
                    selected = store._check_data_path(Path(record["path"]))
                    if sha256(selected) != record["source_sha256"]:
                        raise ValueError("Catalog file changed before export")
                    # Read the captured immutable path, never reselect current.
                    frame = store._read_parquet(selected, None, target_date, None, "date", ticker).copy()
                    if sha256(selected) != record["source_sha256"]:
                        raise ValueError("Catalog file changed during export")
                    if frame.empty:
                        continue
                    # Match the canonical normalizer's closed source vocabulary.
                    # MOOMOO also covers explicit provider/price_type inputs; do
                    # not relabel those original rows as MOOMOO_OPEND.
                    if not frame.source.astype(str).str.upper().isin({"MOOMOO_OPEND", "MOOMOO"}).all() or not frame.adjustment.eq(adjustment).all():
                        raise ValueError("Export source or adjustment contract mismatch")
                    source_labels.update(frame.source.astype(str))
                    dates = frame.date.astype(str).str[:10]
                    if target_date in set(dates):
                        target_set.add(ticker)
                    exported_set.add(ticker)
                    last = max(last, dates.max())
                    frame["date"] = dates
                    frame["moomoo_symbol"] = frame.provider_code
                    frame["market"] = "US"
                    frame["source_policy"] = "MOOMOO_ONLY"
                    frame["snapshot_id"] = snapshot_id
                    frame["fetched_at_utc"] = frame.observed_at.fillna("")
                    for row in frame[FIELDS].to_dict("records"):
                        writer.writerow(row)
                    count += len(frame)
            except BaseException:
                handle.close()
                temporary.unlink()
                raise
        digest = sha256(temporary)
        if path.exists():
            if sha256(path) != digest:
                temporary.unlink()
                raise FileExistsError("Different bytes at existing immutable snapshot path")
            temporary.unlink()
        else:
            os.replace(temporary, path)
        modes[adjustment] = {"path": str(path), "sha256": digest, "row_count": count, "ticker_count": len(exported_set)}
        targets[adjustment], latest[adjustment], actual_sets[adjustment] = target_set, last, exported_set
    available = targets["raw"] & targets["qfq"]
    missing = sorted(set(common) - available)
    sets_equal = actual_sets["raw"] == actual_sets["qfq"]
    complete = not missing and sets_equal and set(common) == actual_sets["raw"]
    source_family = "MOOMOO" if any(value.upper() == "MOOMOO" for value in source_labels) else "MOOMOO_OPEND"
    manifest = {"schema_version": 2, "snapshot_id": snapshot_id, "created_at_utc": utc_now(),
                "source_policy": "MOOMOO_ONLY", "source": source_family, "source_labels": sorted(source_labels),
                "source_label_policy": "PRESERVE_VALIDATED_NORMALIZED_INPUT_LABELS",
                "selection_scope": selection_scope,
                "target_date": target_date, "latest_date": target_date if complete else "",
                "target_date_ticker_count": len(available), "paired_symbol_count": len(common),
                "unpaired_symbols": sorted(set(by_mode["raw"]) ^ set(by_mode["qfq"])),
                "exported_tickers": {a: sorted(values) for a, values in actual_sets.items()},
                "latest_available_dates": latest, "missing_target_date_tickers": missing,
                "model_safe_count": None, "model_safe_status": "NOT_EVALUATED_BY_DATA_MAINTENANCE",
                "files": modes, "catalog_path": str(store.catalog_path), "catalog_input_identity": identity,
                "coverage_status": "COMPLETE_PAIRED_TARGET_DATE" if complete else "INCOMPLETE_TARGET_DATE",
                "research_only": True, "broker_action_allowed": False, "official_adoption_allowed": False}
    manifest_path = root / "canonical_manifest.json"
    if not manifest_path.exists():
        atomic_json(manifest_path, manifest)
    else:
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous.get("catalog_input_identity") != identity or previous.get("files") != modes:
            raise ValueError("Existing manifest content identity conflict")
        manifest = previous
    pointer = {"policy_version": "V21.231", "snapshot_id": snapshot_id, "created_at_utc": manifest["created_at_utc"],
               "cache_root": str(store.paths.cache_root), "canonical_snapshot_dir": str(root),
               "canonical_manifest_path": str(manifest_path), "canonical_manifest_sha256": sha256(manifest_path),
               "canonical_raw_path": modes["raw"]["path"], "canonical_qfq_path": modes["qfq"]["path"],
               "source": source_family, "source_labels": sorted(source_labels),
               "source_policy": "MOOMOO_ONLY", "canonical_as_of_date": target_date,
               "target_date": target_date, "target_date_ticker_count": len(available),
               "expected_universe_count": len(common), "target_date_coverage_ratio": len(available) / len(common),
               "missing_target_date_tickers": missing, "stale_ticker_count": len(missing),
               "canonical_complete_universe_date": target_date if complete else "",
               "raw_qfq_ticker_set_exact_match": sets_equal,
               "raw_qfq_target_date_ticker_set_exact_match": targets["raw"] == targets["qfq"],
               "selection_scope": selection_scope, "coverage_status": manifest["coverage_status"],
               "model_safe_count": None, "model_safe_status": manifest["model_safe_status"],
               "research_only": True, "broker_action_allowed": False, "official_adoption_allowed": False,
               "yfinance_used": False, "yahoo_used": False, "external_fallback_used": False}
    report_root.mkdir(parents=True, exist_ok=True)
    candidate = report_root / "candidate_canonical_pointer.json"
    atomic_json(candidate, pointer)
    backup = mirror_backup = None
    if publish_pointer:
        if not complete:
            raise ValueError("LEGACY_PUBLICATION_BLOCKED_INCOMPLETE_SCOPE_TARGET_DATE")
        backup, mirror_backup = commit_pointer(current, pointer, original, scope_path, scope_bytes, report_root, modes)
    result = {"snapshot_id": snapshot_id, "mode": "PUBLISHED" if publish_pointer else "PREPARED_ONLY",
              "pointer_changed": bool(publish_pointer), "current_pointer": str(current), "candidate_pointer": str(candidate),
              "prior_pointer_backup": str(backup) if backup else None,
              "prior_csv_pointer_backup": str(mirror_backup) if mirror_backup else None,
              "manifest": str(manifest_path), "paired_symbols": len(common), "target_date_covered": len(available),
              "selection_scope": selection_scope, "coverage_status": manifest["coverage_status"], "latest_available_dates": latest}
    atomic_json(report_root / "publication_report.json", result)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target-date", required=True)
    ap.add_argument("--report-root", required=True, type=Path)
    ap.add_argument("--publish-pointer", action="store_true", help="requires an existing matching legacy scope contract and complete coverage")
    args = ap.parse_args()
    print(json.dumps(publish(DataStore(), args.target_date, args.report_root, publish_pointer=args.publish_pointer), ensure_ascii=False))


if __name__ == "__main__":
    main()
