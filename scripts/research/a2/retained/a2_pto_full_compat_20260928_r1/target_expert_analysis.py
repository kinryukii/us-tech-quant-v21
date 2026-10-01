"""Summarize saved same-account target experts from completed replay batches.

This is an analysis of proposed targets and solver diagnostics. It neither loads
NAV/returns nor constructs independent expert accounts. Every cache input is
bound by its complete-file SHA256, including NPZ and raw ledger partitions.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import time

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "analysis"
EPS = 1e-12
PROJECTION_EPS = 1e-10
VERSION = "SAME_ACCOUNT_TARGET_EXPERT_ANALYSIS_V1"


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(ok, message):
    if not bool(ok):
        raise RuntimeError(message)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temp, path)


def atomic_csv(path, frame):
    temp = Path(path).with_name(Path(path).name + ".tmp")
    frame.to_csv(temp, index=False)
    os.replace(temp, path)


class Moments:
    def __init__(self):
        self.n = 0
        self.metrics = {}
        self.statuses = Counter()
        self.counts = Counter()

    def add(self, values, status=None):
        self.n += 1
        if status is not None:
            self.statuses[str(status)] += 1
        for name, value in values.items():
            value = float(value)
            require(np.isfinite(value), "NONFINITE_ANALYSIS_METRIC:" + name)
            a = self.metrics.setdefault(name, [0., 0., value, value])
            a[0] += value
            a[1] += value * value
            a[2] = min(a[2], value)
            a[3] = max(a[3], value)

    def row(self):
        result = {"signal_days": self.n, "solver_status_counts_json": json.dumps(dict(sorted(self.statuses.items())), sort_keys=True)}
        for name, (total, squares, smallest, largest) in self.metrics.items():
            mean = total / self.n
            result.update({name + "_sum": total, name + "_mean": mean,
                           name + "_std": float(np.sqrt(max(0., squares / self.n - mean * mean))),
                           name + "_min": smallest, name + "_max": largest})
        result.update(self.counts)
        return result


def json_record(payload):
    return json.loads(payload.decode("utf-8-sig"))


def source_bytes(batch, relative, hashes):
    payload = (batch / relative).read_bytes()
    hashes[str(relative)] = hashlib.sha256(payload).hexdigest()
    return payload


def source_names(batch):
    return {"COMPLETE.json", "metadata.json"} | {
        str(p.relative_to(batch)) for folder, pattern in [("raw_model_outputs", "*.parquet"),
                                                       ("decision_coverage", "*_experts.npz")]
        for p in (batch / folder).glob(pattern)}


def batch_tables(batch, year, registered, members, freeze, producer_sha):
    cache = OUT / "target_expert_cache" / producer_sha[:16] / str(year) / batch.name
    manifest_path = cache / "MANIFEST.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        require(manifest["freeze_sha256"] == sha(ROOT / "FREEZE.json"), "CACHED_FREEZE_CHANGED")
        require(source_names(batch) == set(manifest["source_sha256"]), "COMPLETED_BATCH_FILE_SET_CHANGED:" + str(batch))
        for name, digest in manifest["source_sha256"].items():
            require(sha(batch / name) == digest, "COMPLETED_BATCH_SOURCE_CHANGED:" + str(batch / name))
        for name, digest in manifest["output_sha256"].items():
            require(sha(cache / name) == digest, "TARGET_EXPERT_CACHE_CHANGED:" + str(cache / name))
        return pd.read_parquet(cache / "EXPERT_SUMMARY.parquet"), pd.read_parquet(cache / "DECISION_SUMMARY.parquet"), manifest, True

    hashes = {}
    complete = json_record(source_bytes(batch, Path("COMPLETE.json"), hashes))
    require(complete["status"] == "REPLAYED" and complete["year"] == year, "INVALID_COMPLETE_RECEIPT:" + str(batch))
    require(complete["policy_sha256"] == freeze["artifact_sha256"]["policy.py"]
            and complete["engine_sha256"] == freeze["artifact_sha256"]["batch_engine.py"]
            and complete["new_fit_calls"] == 0, "BATCH_NOT_MATCHING_FROZEN_POLICY_ENGINE")
    metadata = json_record(source_bytes(batch, Path("metadata.json"), hashes))
    require(hashes["metadata.json"] == complete["metadata_sha256"], "COMPLETED_METADATA_HASH_MISMATCH")
    ids = metadata["strategy_ids"]
    require(len(ids) == len(set(ids)) and set(ids) == set(complete["strategies"]), "BATCH_STRATEGY_IDS_MISMATCH")
    require(all(s in registered for s in ids), "UNREGISTERED_BATCH_STRATEGY")
    target_ids = [s for s in ids if registered[s]["target_fusion"] != "none"]
    require(len(target_ids) == 8, "EXPECTED_EIGHT_TARGET_FUSION_ACCOUNTS_PER_BATCH")
    require("every expert uses that fusion strategy's actual account state" in metadata["target_fusion_expert_scope"], "UNKNOWN_EXPERT_ACCOUNT_SCOPE")
    tickers = metadata["tickers"]
    require(len(tickers) == len(set(tickers)), "DUPLICATE_TICKER_COLUMNS")
    raw_parts = []
    raw_columns = ["strategy_id", "signal_date", "decision_id", "raw_matrix_strategy_row",
                   "expert_matrix_path", "raw_model_outputs_json"]
    for part in sorted((batch / "raw_model_outputs").glob("*.parquet")):
        payload = source_bytes(batch, part.relative_to(batch), hashes)
        raw_parts.append(pd.read_parquet(io.BytesIO(payload), columns=raw_columns,
                                       filters=[("strategy_id", "in", target_ids)]))
    require(bool(raw_parts), "MISSING_RAW_MODEL_LEDGER")
    raw = pd.concat(raw_parts, ignore_index=True)
    raw["signal_date"] = pd.to_datetime(raw.signal_date)
    require(not raw.duplicated(["signal_date", "strategy_id"]).any(), "DUPLICATE_TARGET_RAW_DECISION")
    raw = raw.set_index(["signal_date", "strategy_id"])
    files = sorted((batch / "decision_coverage").glob("*_experts.npz"))
    require(bool(files), "MISSING_EXPERT_MATRICES")
    calendar_file = ROOT / "data" / ("pre_calendar.parquet" if year == 2025 else "test_calendar.parquet")
    cal = pd.to_datetime(pd.read_parquet(calendar_file, columns=["trade_date"]).trade_date)
    expected_days = set(cal[(cal >= pd.Timestamp(metadata["signal_start"])) & (cal <= pd.Timestamp(metadata["signal_end"]))])
    matrix_days = {pd.Timestamp(p.name[:8]) for p in files}
    require(matrix_days == expected_days, "EXPERT_SIGNAL_DATE_COVERAGE_MISMATCH")
    require(set(raw.index) == {(date, s) for date in expected_days for s in target_ids}, "TARGET_RAW_STRATEGY_DATE_COVERAGE_MISMATCH")
    experts_acc = {(s, member): Moments() for s in target_ids for member in members}
    decision_acc = {s: Moments() for s in target_ids}
    reconstruction_error = 0.
    for path in files:
        date = pd.Timestamp(path.name[:8])
        payload = source_bytes(batch, path.relative_to(batch), hashes)
        with np.load(io.BytesIO(payload), allow_pickle=False) as saved:
            targets = np.asarray(saved["targets"], dtype=float)
            indices = np.asarray(saved["rowindices"], dtype=int)
            names = saved["expert_names"].tolist()
        require(names == members and targets.shape == (len(target_ids), len(members), len(tickers)), "EXPERT_MATRIX_SHAPE_OR_MEMBER_ORDER_MISMATCH")
        require(len(indices) == len(set(indices.tolist())) and (indices >= 0).all() and (indices < len(ids)).all(), "INVALID_EXPERT_ACCOUNT_ROW_MAP")
        mapped = [ids[i] for i in indices]
        require(set(mapped) == set(target_ids), "EXPERT_ACCOUNT_ROW_MAP_COVERAGE_MISMATCH")
        require(np.isfinite(targets).all() and targets.min() >= -EPS, "NONFINITE_OR_NEGATIVE_EXPERT_TARGET")
        for j, strategy in enumerate(mapped):
            source = raw.loc[(date, strategy)]
            require(int(source.raw_matrix_strategy_row) == int(indices[j])
                    and source.decision_id == f"{strategy}|{date.date()}"
                    and Path(source.expert_matrix_path) == path.relative_to(batch), "EXPERT_RAW_DECISION_LINK_MISMATCH")
            meta = json.loads(source.raw_model_outputs_json)
            spec = registered[strategy]
            require(meta["strategy_id"] == strategy and pd.Timestamp(meta["signal_date"]) == date
                    and all(meta[k] == spec[k] for k in ["axis", "risk", "optimizer"]), "RAW_POLICY_METADATA_MISMATCH")
            require(set(meta["expert_solver_statuses"]) == set(members)
                    and set(meta["expert_solver_residuals"]) == set(members), "EXPERT_SOLVER_METADATA_MISSING")
            a = targets[j]
            equal = a.mean(axis=0)
            median = np.median(a, axis=0)
            fused = equal if spec["target_fusion"] == "target_equal" else median
            gross = a.sum(axis=1)
            positive = a > EPS
            expert_names = positive.sum(axis=1)
            l1_equal = np.abs(a - equal).sum(axis=1)
            l1_median = np.abs(a - median).sum(axis=1)
            l1_registered = l1_equal if spec["target_fusion"] == "target_equal" else l1_median
            error = abs(float(fused.sum()) - meta["raw_gross"])
            reconstruction_error = max(reconstruction_error, error)
            require(error <= 1e-9 and int((fused > 0).sum()) == meta["selected_count"], "PREFUSION_TARGET_RECONSTRUCTION_MISMATCH")
            require(abs(meta["gross_gap_vs_reference"] - (meta["final_gross"] - meta["reference_gross"])) <= 1e-9, "REFERENCE_GROSS_GAP_IDENTITY_FAILURE")
            require(meta["component_projection_l1"] + 1e-9 >= abs(meta["final_gross"] - meta["raw_gross"])
                    and meta["component_projection_l1"] <= meta["axis_replacement_l1"] + meta["slot_projection_l1"] + 1e-9, "PROJECTION_L1_IDENTITY_FAILURE")
            median_positive = median > EPS
            ties = np.isclose(a, median[None, :], atol=EPS, rtol=0.) & median_positive[None, :]
            tie_counts = ties.sum(axis=0)
            median_shares = np.divide(ties, tie_counts[None, :], out=np.zeros_like(a), where=tie_counts[None, :] > 0).sum(axis=1)
            for e, member in enumerate(members):
                acc = experts_acc[(strategy, member)]
                status = meta["expert_solver_statuses"][member]
                acc.add({"expert_gross": gross[e], "expert_names": expert_names[e],
                         "l1_to_equal_prefusion": l1_equal[e], "l1_to_median_prefusion": l1_median[e],
                         "l1_to_registered_prefusion": l1_registered[e], "daily_max_target_weight": a[e].max(),
                         "expert_solver_residual": meta["expert_solver_residuals"][member],
                         "median_positive_coordinate_tie_share": median_shares[e]}, status)
                acc.counts["ticker_cells"] += len(tickers)
                acc.counts["zero_target_cells"] += int((~positive[e]).sum())
                acc.counts["positive_target_cells"] += int(positive[e].sum())
                acc.counts["positive_target_weight_sum"] += float(a[e, positive[e]].sum())
                acc.counts["at_weight_cap_positive_cells"] += int((a[e] >= metadata["max_target_weight"] - 1e-9).sum())
                acc.counts["zero_active_target_days"] += int(abs(gross[e]) <= EPS)
                acc.counts["approximate_budget_days"] += int(status == "APPROXIMATE_BUDGET")
                acc.counts["failed_preserve_units_days"] += int(status == "FAILED_PRESERVE_UNITS")
                acc.counts["no_valid_input_days"] += int(status == "NO_VALID_INPUT")
            account = decision_acc[strategy]
            metric_names = ["raw_gross", "final_gross", "component_projection_l1", "reference_gross",
                            "gross_gap_vs_reference", "axis_replacement_l1", "slot_projection_l1", "selected_count"]
            account.add({**{k: meta[k] for k in metric_names}, "prefusion_gross": fused.sum(),
                         "prefusion_names_gt_eps": int((fused > EPS).sum()),
                         "same_account_equal_vs_median_l1": np.abs(equal - median).sum(),
                         "expert_l1_to_registered_prefusion_mean": l1_registered.mean(),
                         "expert_gross_range": gross.max() - gross.min(),
                         "zero_expert_fraction": float((np.abs(gross) <= EPS).mean()),
                         "expert_residual_max": max(meta["expert_solver_residuals"].values())}, meta["solver_status"])
            account.counts["axis_replacement_days"] += int(meta["axis_replacement_l1"] > PROJECTION_EPS)
            account.counts["slot_projection_days"] += int(meta["slot_projection_l1"] > PROJECTION_EPS)
            account.counts["component_projection_days"] += int(meta["component_projection_l1"] > PROJECTION_EPS)
            account.counts["zero_prefusion_target_days"] += int(abs(fused.sum()) <= EPS)
            account.counts["zero_final_policy_target_days"] += int(abs(meta["final_gross"]) <= EPS)
            account.counts["expert_approximate_budget_decisions"] += sum(v == "APPROXIMATE_BUDGET" for v in meta["expert_solver_statuses"].values())
            account.counts["expert_failed_preserve_units_decisions"] += sum(v == "FAILED_PRESERVE_UNITS" for v in meta["expert_solver_statuses"].values())

    expert_rows, decision_rows = [], []
    for strategy in target_ids:
        spec = registered[strategy]
        common = {"year": year, "strategy": strategy, "risk": spec["risk"], "optimizer": spec["optimizer"],
                  "axis": spec["axis"], "target_fusion": spec["target_fusion"], "batch": batch.name,
                  "coverage_status": "OBSERVED_COMPLETE_BATCH"}
        for member in members:
            acc = experts_acc[(strategy, member)]
            require(acc.n == len(expected_days), "EXPERT_DAILY_COVERAGE_GAP")
            row = {**common, "member": member, **acc.row()}
            row.update(zero_target_cell_fraction=acc.counts["zero_target_cells"] / acc.counts["ticker_cells"],
                       zero_active_target_day_fraction=acc.counts["zero_active_target_days"] / acc.n,
                       positive_target_weight_mean=acc.counts["positive_target_weight_sum"] / acc.counts["positive_target_cells"] if acc.counts["positive_target_cells"] else None,
                       at_weight_cap_fraction_of_positive=acc.counts["at_weight_cap_positive_cells"] / acc.counts["positive_target_cells"] if acc.counts["positive_target_cells"] else None,
                       equal_additive_gross_contribution_mean=row["expert_gross_mean"] / len(members) if spec["target_fusion"] == "target_equal" else None,
                       contribution_scope="same_account_active_targets_before_fusion_axis_slot_projection")
            expert_rows.append(row)
        account = decision_acc[strategy]
        require(account.n == len(expected_days), "TARGET_ACCOUNT_DAILY_COVERAGE_GAP")
        decision_rows.append({**common, **account.row(),
                              "axis_replacement_day_fraction": account.counts["axis_replacement_days"] / account.n,
                              "slot_projection_day_fraction": account.counts["slot_projection_days"] / account.n,
                              "component_projection_day_fraction": account.counts["component_projection_days"] / account.n,
                              "max_prefusion_reconstruction_error": reconstruction_error})
    expert_frame, decision_frame = pd.DataFrame(expert_rows), pd.DataFrame(decision_rows)
    require(source_names(batch) == set(hashes), "COMPLETED_BATCH_CHANGED_DURING_SOURCE_SCAN")
    require(all(sha(batch / name) == digest for name, digest in hashes.items()), "COMPLETED_SOURCE_BYTES_CHANGED_DURING_ANALYSIS")
    cache.mkdir(parents=True, exist_ok=True)
    expert_frame.to_parquet(cache / "EXPERT_SUMMARY.parquet", index=False)
    decision_frame.to_parquet(cache / "DECISION_SUMMARY.parquet", index=False)
    manifest = {"version": VERSION, "year": year, "batch": batch.name, "producer_sha256": producer_sha,
                "freeze_sha256": sha(ROOT / "FREEZE.json"), "source_sha256": hashes,
                "output_sha256": {name: sha(cache / name) for name in ["EXPERT_SUMMARY.parquet", "DECISION_SUMMARY.parquet"]},
                "target_strategies": target_ids, "expert_rows": len(expert_frame), "decision_rows": len(decision_frame),
                "signal_days": len(expected_days), "max_prefusion_reconstruction_error": reconstruction_error}
    atomic_json(manifest_path, manifest)
    return expert_frame, decision_frame, manifest, False


def run_once():
    OUT.mkdir(parents=True, exist_ok=True)
    producer_sha = sha(Path(__file__))
    frozen = json.loads((ROOT / "FREEZE.json").read_text(encoding="utf-8"))
    registry = json.loads((ROOT / "REGISTRY.json").read_text(encoding="utf-8"))
    require(frozen["status"] == "FROZEN_ALL_LEARNING_PRE2026", "COMPLETE_BATCH_FREEZE_REQUIRED")
    require(sha(ROOT / "REGISTRY.json") == frozen["artifact_sha256"]["REGISTRY.json"], "FROZEN_REGISTRY_CHANGED")
    registered = {p["strategy"]: p for p in registry["strategies"]}
    target = {s: p for s, p in registered.items() if p["target_fusion"] != "none"}
    require(len(target) == 288, "EXPECTED_288_REGISTERED_TARGET_STRATEGIES")
    members = next(iter(target.values()))["members"]
    require(len(members) == 13 and len(set(members)) == 13 and all(p["members"] == members for p in target.values()), "TARGET_EXPERT_REGISTRY_MISMATCH")
    expert_parts, decision_parts, batch_receipts, pending = [], [], [], []
    completed_batch_counts, new_batches, cached_batches = {}, 0, 0
    for year in [2025, 2026]:
        completed_batch_counts[str(year)] = 0
        for batch in sorted((ROOT / f"results/{year}").glob("batch_*")):
            if not (batch / "COMPLETE.json").exists():
                continue
            try:
                json.loads((batch / "COMPLETE.json").read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pending.append(str(batch.relative_to(ROOT)))
                continue
            expert, decision, manifest, reused = batch_tables(batch, year, registered, members, frozen, producer_sha)
            expert_parts.append(expert)
            decision_parts.append(decision)
            completed_batch_counts[str(year)] += 1
            cached_batches += int(reused)
            new_batches += int(not reused)
            batch_receipts.append({"year": year, "batch": batch.name,
                                   "manifest_path": str((OUT / "target_expert_cache" / producer_sha[:16] / str(year) / batch.name / "MANIFEST.json").relative_to(ROOT)),
                                   "source_files": len(manifest["source_sha256"]), "signal_days": manifest["signal_days"],
                                   "expert_rows": manifest["expert_rows"], "cache_reused": reused,
                                   "max_prefusion_reconstruction_error": manifest["max_prefusion_reconstruction_error"]})
            print("TARGET_EXPERT_BATCH", year, batch.name, "CACHE_VERIFIED" if reused else "ANALYZED", manifest["expert_rows"], flush=True)
    observed_experts = pd.concat(expert_parts, ignore_index=True) if expert_parts else pd.DataFrame(columns=["year", "strategy", "member"])
    observed_decisions = pd.concat(decision_parts, ignore_index=True) if decision_parts else pd.DataFrame(columns=["year", "strategy"])
    require(not observed_experts.duplicated(["year", "strategy", "member"]).any(), "DUPLICATE_EXPERT_SUMMARY_KEYS")
    require(not observed_decisions.duplicated(["year", "strategy"]).any(), "DUPLICATE_TARGET_ACCOUNT_SUMMARY_KEYS")
    base_rows = [{"year": year, "strategy": s, "member": member} for year in [2025, 2026] for s in target for member in members]
    expected_experts = pd.DataFrame(base_rows)
    expected_decisions = expected_experts[["year", "strategy"]].drop_duplicates().reset_index(drop=True)
    require(len(expected_experts) == 7488 and len(expected_decisions) == 576, "EXPECTED_TARGET_COVERAGE_SIZE_CHANGED")
    experts = expected_experts.merge(observed_experts, on=["year", "strategy", "member"], how="left", validate="one_to_one")
    decisions = expected_decisions.merge(observed_decisions, on=["year", "strategy"], how="left", validate="one_to_one")
    for frame in [experts, decisions]:
        if "coverage_status" not in frame:
            frame["coverage_status"] = "NOT_COMPLETED"
        else:
            frame["coverage_status"] = frame.coverage_status.fillna("NOT_COMPLETED")
        for name in ["risk", "optimizer", "axis", "target_fusion"]:
            frame[name] = frame.strategy.map(lambda s: target[s][name])
    expert_path = OUT / "TARGET_EXPERT_CONTRIBUTIONS.csv"
    decision_path = OUT / "TARGET_FUSION_DECISION_SUMMARY.csv"
    atomic_csv(expert_path, experts)
    atomic_csv(decision_path, decisions)
    complete = len(observed_experts) == 7488 and len(observed_decisions) == 576
    if complete:
        require(all(n == 36 for n in completed_batch_counts.values()), "EXPECTED_36_BATCHES_PER_YEAR")
    receipt = {"status": "COMPLETE_SAME_ACCOUNT_TARGET_CONTRIBUTIONS" if complete else "PARTIAL_AWAITING_COMPLETED_REPLAY_BATCHES",
               "created_utc": datetime.now(timezone.utc).isoformat(), "version": VERSION, "complete": complete,
               "producer_sha256": producer_sha, "freeze_sha256": sha(ROOT / "FREEZE.json"),
               "registry_sha256": sha(ROOT / "REGISTRY.json"), "completed_batches": completed_batch_counts,
               "new_batches_analyzed": new_batches, "cached_batches_revalidated": cached_batches,
               "expected_expert_rows": 7488, "observed_expert_rows": len(observed_experts),
               "pending_expert_rows": 7488 - len(observed_experts), "saved_expert_coverage_rows": len(experts),
               "expected_target_account_rows": 576, "observed_target_account_rows": len(observed_decisions),
               "source_batches": batch_receipts, "incomplete_complete_receipts_skipped": pending,
               "output_sha256": {p.name: sha(p) for p in [expert_path, decision_path]},
               "fit_calls": 0, "new_candidates": 0, "nav_or_return_files_read": 0, "hypothetical_expert_accounts_created": 0,
               "metric_definitions": {"scope": "Each expert optimizes against the target-fusion strategy's same actual account. Saved proposals are active decision targets, not separate accounts or NAVs.",
                   "gross": "Sum of expert active target weights. Reserved holdings carried by the engine are excluded; zero active targets need not mean an all-cash account.",
                   "names": "Ticker coordinates with target weight > 1e-12; the fixed market ticker grid includes names without decision-day input.",
                   "zero_target_cells": "Targets <= 1e-12 across the full fixed market ticker grid. This also reflects TOP20/candidate restrictions; it is not a learning score.",
                   "prefusion": "Recomputed equally weighted mean or per-ticker median of the 13 experts before axis replacement and slot projection.",
                   "equal_contribution": "For registered target_equal accounts only, expert gross/13 is an additive contribution to preprojection gross.",
                   "median_tie_share": "Fractional counts of positive median ticker coordinates attained by each expert, splitting numeric ties within 1e-12. These are coordinate selection counts, not additive target weights.",
                   "solver": "All expert status counts are preserved; residuals are read from the same decision JSON. A zero failure residual is not counted as solver success.",
                   "projection": "Policy axis/slot/component effects and reference gross are before the common engine's execution/adaptation; they do not establish filled weights or account exposure.",
                   "dispersion": "L1 to equal, median and the registered prefusion vector is descriptive same-account target disagreement; no new account is evaluated.",
                   "std": "Population standard deviation across complete-batch signal days; sums have target-weight-day/name-day/L1-day units.",
                   "cache": "Every cached complete source file is rehashed before reuse; original NPZ/ledger files are never modified."},
               "formal_2026_full_pool_status": "BLOCKED_DATA"}
    atomic_json(OUT / "TARGET_FUSION_DECISION_RECEIPT.json", receipt)
    print(json.dumps({k: receipt[k] for k in ["status", "completed_batches", "observed_expert_rows", "pending_expert_rows", "complete"]}), flush=True)
    return receipt


def self_test():
    acc = Moments()
    acc.add({"gross": 0.}, "FAILED_PRESERVE_UNITS")
    acc.add({"gross": .5}, "APPROXIMATE_BUDGET")
    acc.add({"gross": 1.}, "SOLVED_TOLERANCE")
    row = acc.row()
    require(abs(row["gross_mean"] - .5) < 1e-15 and abs(row["gross_std"] - np.sqrt(1 / 6)) < 1e-15,
            "MOMENT_AGGREGATION_TEST_FAILED")
    require(json.loads(row["solver_status_counts_json"])["FAILED_PRESERVE_UNITS"] == 1, "FAILED_STATUS_WAS_DROPPED")
    a = np.zeros((13, 3))
    a[:6, 0] = .1
    a[6:, 1] = .1
    equal, median = a.mean(0), np.median(a, axis=0)
    require(np.isclose(equal.sum(), .1) and np.array_equal(median, [0., .1, 0.]), "MEAN_MEDIAN_DIFFERENCE_TEST_FAILED")
    require(np.isclose((a.sum(1) / 13).sum(), equal.sum()) and (np.abs(a - median).sum(1) > 0).sum() == 6,
            "CONTRIBUTION_AND_ZERO_COORDINATE_TEST_FAILED")
    print("TARGET_EXPERT_SELF_TEST_PASS", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=30.)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        require(1 <= args.poll_seconds <= 60, "POLL_INTERVAL_MUST_BE_1_TO_60_SECONDS")
        last_snapshot = None
        while True:
            snapshot = tuple((str(p), sha(p)) for year in [2025, 2026]
                             for p in sorted((ROOT / f"results/{year}").glob("batch_*/COMPLETE.json")))
            if snapshot != last_snapshot:
                receipt = run_once()
                last_snapshot = snapshot
                if receipt["complete"]:
                    break
            if not args.watch:
                if args.require_complete and not receipt["complete"]:
                    raise SystemExit(2)
                break
            time.sleep(args.poll_seconds)
