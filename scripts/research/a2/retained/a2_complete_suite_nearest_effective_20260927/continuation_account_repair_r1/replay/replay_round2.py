"""Conservative price-date quarantine around the frozen R6 account engine.

All fills, policy decisions, costs and state transitions still come from the
original engine via replay_account.run_path. This wrapper only masks exact
unresolved fields before they can be consumed and checks the prior prefix.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import replay_account as base


HERE = Path(__file__).resolve().parent


def quarantine(prices: pd.DataFrame, approved: list[dict], ledger: Path) -> tuple[pd.DataFrame, list[dict]]:
    entries = pd.read_csv(ledger, dtype={"ticker": str, "trade_date": str, "field": str,
                                         "evidence_id": str, "reason": str,
                                         "candidate_pool_version": str})
    required = {"ticker", "trade_date", "field", "evidence_id", "reason", "candidate_pool_version"}
    if not required <= set(entries):
        raise ValueError(f"quarantine ledger missing {sorted(required - set(entries))}")
    if entries.empty or entries.duplicated(["ticker", "trade_date", "field"]).any():
        raise ValueError("quarantine ledger empty or has duplicate field keys")
    if not entries.candidate_pool_version.eq("R6_UNCHANGED").all():
        raise ValueError("quarantine would change candidate pool version")
    if not entries.field.isin(["open", "close"]).all():
        raise ValueError("quarantine field must be open or close")
    if entries[["ticker", "trade_date", "field", "evidence_id", "reason"]].isna().any().any():
        raise ValueError("quarantine ledger has null required value")
    approved_fields = {(row["ticker"], row["trade_date"], field)
                       for row in approved for field in ("open", "close")
                       if row[f"{field}_authorized"]}
    result = prices.copy()
    index = result.set_index(["ticker", "trade_date"])
    masked = []
    for row in entries.itertuples(index=False):
        when = pd.Timestamp(row.trade_date)
        key = (row.ticker, when)
        flat = (row.ticker, when.date().isoformat(), row.field)
        if flat in approved_fields:
            raise ValueError(f"approval/quarantine collision: {flat}")
        if key not in index.index:
            raise ValueError(f"quarantine has no frozen price row: {flat}")
        value = index.loc[key, row.field]
        if not np.isfinite(value) or value <= 0:
            raise ValueError(f"quarantine field already unavailable: {flat}")
        index.loc[key, row.field] = np.nan
        masked.append({"ticker": row.ticker, "trade_date": flat[1], "field": row.field,
                       "previous_frozen_value": float(value), "evidence_id": row.evidence_id,
                       "reason": row.reason})
    return index.reset_index(), masked


def reconcile_prior_prefix(new_dir: Path, prior_dir: Path, run_id: str, through: str) -> dict:
    date = pd.Timestamp(through)
    columns = {"daily": "date", "positions": "date", "trades": "execution_date",
               "target_decisions": "signal_date", "diagnostics": "date"}
    counts = {}
    hashes = {}
    for name, date_column in columns.items():
        old_path = prior_dir / run_id / f"{name}.parquet"
        new_path = new_dir / run_id / f"{name}.parquet"
        old = pd.read_parquet(old_path)
        new = pd.read_parquet(new_path)
        old = old.loc[old[date_column].le(date)].reset_index(drop=True).dropna(axis=1, how="all")
        new = new.loc[new[date_column].le(date)].reset_index(drop=True).dropna(axis=1, how="all")
        pd.testing.assert_frame_equal(new, old, check_dtype=False, check_exact=True)
        counts[name] = len(new)
        hashes[name] = base.digest(old_path)
    return {"same_account_prefix_through": through, "method": "exact five-table DataFrame equality",
            "row_counts": counts, "prior_ledger_hashes": hashes}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--approval-ledger", type=Path, required=True)
    parser.add_argument("--quarantine-ledger", type=Path, required=True)
    parser.add_argument("--prior-prefix-dir", type=Path, required=True)
    parser.add_argument("--paths", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise RuntimeError(f"output exists; preserve prior run: {output}")
    source_hashes = base.frozen_sources()
    fit_guard = base.forbid_fitting()
    prices, applied = base.load_prices(args.approval_ledger)
    prices, masked = quarantine(prices, applied, args.quarantine_ledger)
    panel = base.load_policy_panel()
    calendar = pd.DatetimeIndex(pd.read_parquet(base.CALENDAR_PATH).query("is_test").trade_date)
    if calendar[-1] != base.TERMINAL or max(panel.signal_date) != base.SIGNAL_END:
        raise RuntimeError("frozen R6 calendar or signal window changed")
    roster = {f"{name}_{cost}bps": (name, cost) for cost in base.SCENARIOS for name in base.TEST_NAMES}
    if len(args.paths) != len(set(args.paths)) or any(run_id not in roster for run_id in args.paths):
        raise ValueError("unknown or duplicate run id")
    output.mkdir(parents=True, exist_ok=False)
    base.save_json(output / "SOURCE_HASHES.json", {
        "frozen_source_hashes": source_hashes,
        "actual_run_replay_source": {"path": str(Path(base.run_replay.__code__.co_filename).resolve()),
                                     "sha256": base.digest(Path(base.run_replay.__code__.co_filename))},
        "adapter_sources": {"replay_account.py": base.digest(HERE / "replay_account.py"),
                            "replay_round2.py": base.digest(Path(__file__))},
        "approval_ledger": {"path": str(args.approval_ledger.resolve()), "sha256": base.digest(args.approval_ledger)},
        "quarantine_ledger": {"path": str(args.quarantine_ledger.resolve()), "sha256": base.digest(args.quarantine_ledger)},
        "prior_prefix_dir": str(args.prior_prefix_dir.resolve()),
        "seal_files": {f"cost_{cost}": {"path": str(base.EVALUATION / f"cost_{cost}" / "FROZEN_BEFORE_SCORING.json"),
                                        "sha256": base.digest(base.EVALUATION / f"cost_{cost}" / "FROZEN_BEFORE_SCORING.json")}
                       for cost in base.SCENARIOS}})
    diff_rows = [{"ticker": row["ticker"], "trade_date": row["trade_date"], "field": field,
                  "change_kind": "approved_restore", "old_field_value": None,
                  "new_field_value": row[f"{field}_value"], "evidence_id": row["evidence_id"]}
                 for row in applied for field in ("open", "close") if row[f"{field}_authorized"]]
    diff_rows.extend({"ticker": row["ticker"], "trade_date": row["trade_date"], "field": row["field"],
                      "change_kind": "conflict_quarantine", "old_field_value": row["previous_frozen_value"],
                      "new_field_value": None, "evidence_id": row["evidence_id"]} for row in masked)
    pd.DataFrame(diff_rows).to_csv(output / "PRICE_FIELD_DIFF.csv", index=False)
    pd.DataFrame(masked).to_csv(output / "QUARANTINED_FIELDS.csv", index=False)
    manifest_hash = base.digest(output / "SOURCE_HASHES.json")
    diff_hash = base.digest(output / "PRICE_FIELD_DIFF.csv")
    summaries = []
    for run_id in args.paths:
        policy, cost = roster[run_id]
        summary = base.run_path(policy, cost, prices, calendar, panel, output, source_hashes,
                                args.approval_ledger, applied, manifest_hash, diff_hash)
        checkpoint = json.loads((output / run_id / "CHECKPOINT.json").read_text(encoding="utf-8"))
        if not checkpoint["certified_through"]:
            raise AssertionError("GLW quarantine unexpectedly blocks first calendar day")
        comparison = reconcile_prior_prefix(output, args.prior_prefix_dir, run_id,
                                            checkpoint["certified_through"])
        base.save_json(output / run_id / "PRIOR_PREFIX_RECONCILIATION.json", comparison)
        summaries.append(summary)
        base.save_json(output / "PROGRESS.json", {"paths_completed": len(summaries), "paths": summaries,
                                                "fit_guard_attempts": fit_guard["attempts"]})
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    if fit_guard["attempts"] or base.frozen_sources() != source_hashes:
        raise RuntimeError("fit attempted or frozen sources changed")
    base.save_json(output / "COMPLETE.json", {"status": "EVIDENCE_GATED_PREFIXES_ONLY",
                                           "paths": summaries, "source_hashes_checked_before_and_after": len(source_hashes),
                                           "source_seals_checked_before_and_after": len(base.SCENARIOS),
                                           "approved_price_keys": len(applied),
                                           "quarantined_price_fields": len(masked),
                                           "fit_guard_attempts": fit_guard["attempts"],
                                           "formal_full_pool_result": False})


if __name__ == "__main__":
    main()
