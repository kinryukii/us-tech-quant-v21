"""Bounded historical target sampling and six fixed conditional-gross fits.

Engine/bootstrap remains caller-owned. Import performs no data reads or fits.
A pinned source manifest and explicit train release gate every numerical read.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.storage.storage_r2a import write_json_atomic
from scripts.research.a2.training import base_conditioned_gross as gross
from scripts.research.a2.training import stateful_decision_models as models
from scripts.research.a2.training import stateful_values as values
from scripts.research.a2.training.stateful_execution import continuation_lock

TASK = "A_BASE_CONDITIONED_GROSS_6_COMBINATIONS_20261013_R1"
BASES = ("R10_DIRECT_MEAN4_ELASTICNET_MID", "R10_DIRECT_H5_RIDGE_MID")
CUTOFF = pd.Timestamp("2024-10-07")
START = pd.Timestamp("2024-01-02")
CAL_SESSIONS = 60
FIT_CAP = 10
COLUMNS = ("signal_date", "label_mature_date", "basket_y", "target", *gross.FEATURES)
SOURCE_KEYS = ("contract", "historical_pool", "model_bundle", "prepared_bundle",
               "raw_audit", "raw_equivalence", "historical_application", "label_owner")


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def reference(path):
    p = Path(path).resolve()
    with p.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return dict(path=str(p), sha256=digest)


def verify(ref):
    require(reference(ref["path"]) == ref, "SOURCE_REFERENCE_CHANGED")
    return Path(ref["path"])


def document(ref, limit=200_000):
    p = Path(ref["path"])
    require(p.stat().st_size <= limit, "BOUNDED_METADATA_REQUIRED")
    verify(ref)
    return json.loads(p.read_text(encoding="utf-8"))


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def runtime_source_refs():
    return {name: reference(module.__file__) for name, module in
            (("gross_adapter", gross), ("decision", gross.owner),
             ("decision_models", models), ("values", values))} | {
             "native_models": reference(values.NATIVE)}


def history_config():
    return dict(account_start=str(START.date()), initial_cash_usd=3000,
                proxy_warmup_start="2023-01-03", warmup_account_execution=False,
                signal_and_label_cutoff_exclusive=str(CUTOFF.date()),
                base_account_paths=list(BASES), annual_reset=False,
                calibration_sessions=CAL_SESSIONS, calibration_model_selection=False,
                target_capture="SIGNAL_TIME_BASE_POLICY_SAME_CONTROLLABLE_MASK",
                account_orders_role="TRACE_AND_ACTUAL_FEE_DIAGNOSTIC_ONLY")


def manifest_template(run):
    """Metadata-only draft; root fills refs after historical source admission."""
    return dict(task_id=TASK, run_root=str(Path(run).resolve()),
        driver_ref=reference(__file__), runtime_source_refs=runtime_source_refs(),
        history=history_config(), permits=dict(train=False), sample_receipt_ref=None,
        raw_model_manifest_refs={"2023": None, "2024": None},
        resource_owner_ref=None, dependencies=[],
        required_unknown=["sample_receipt_ref", "raw_model_manifest_refs", "resource_owner_ref"])


class SignalTargetRecorder:
    """Wrap the base policy; capture inputs without changing its returned decision.

    feature_provider(di, context, row) -> (ordered security keys, canonical32,
    raw_scores). It is a signal-only bounded reader; it must never load labels.
    Mask mirrors the pinned BaseConditionedGrossOverlay; equivalence is tested.
    """
    def __init__(self, path_ids, base_policy, feature_provider):
        self.path_ids = tuple(path_ids)
        require(self.path_ids == BASES, "EXACT_BASE_ACCOUNT_PATHS_REQUIRED")
        self.base_policy, self.feature_provider = base_policy, feature_provider
        self.records, self.last_date = [], None

    def __call__(self, di, context):
        day = pd.Timestamp(context.signal_date)
        require(START <= day < CUTOFF and tuple(context.path_ids) == self.path_ids
                and (self.last_date is None or day > self.last_date), "BOUNDED_CAUSAL_BASE_SIGNAL")
        decision = self.base_policy(di, context)
        w = np.asarray(decision.weights, float).copy()
        mask = np.asarray(context.decision_mask if decision.explicit_mask is None
                          else decision.explicit_mask, bool).copy()
        require(w.shape == mask.shape == np.asarray(context.current_units).shape,
                "SIGNAL_TARGET_SHAPE")
        pending = []
        for row, base in enumerate(self.path_ids):
            gross._weights(w[row])
            frozen = (np.asarray(context.reserved_mask[row], bool)
                      | ~np.asarray(context.decision_mask[row], bool)
                      | (np.asarray(context.sell_restricted[row], bool)
                         & (np.asarray(context.current_units[row]) > 1e-10)))
            mask[row] &= ~frozen
            w[row, ~mask[row]] = 0.
            if not w[row].sum():
                pending.append(dict(base=base, signal_date=day, status="CASH_NO_LABEL"))
                continue
            keys, x, scores = self.feature_provider(di, context, row)
            keys, x, scores = tuple(keys), np.asarray(x, float), np.asarray(scores, float)
            require(len(keys) == len(w[row]) and len(set(keys)) == len(keys), "UNIQUE_ORDERED_SIGNAL_KEYS")
            gross.aggregate_reference(w[row], x, scores)
            selected = w[row] > 0
            # Constituent selection is complete before any outcome request.
            pending.append(dict(base=base, signal_date=day, status="TARGET_RECORDED",
                keys=tuple(k for k, use in zip(keys, selected) if use),
                weights=w[row, selected].copy(), feature_matrix=x[selected].copy(),
                raw_scores=scores[selected].copy()))
        self.records.extend(pending)
        self.last_date = day
        return decision


def build_samples(records, label_clock, label_values):
    """Clock first, then numeric H5 labels; unavailable labels exclude entire day.

    label_clock(record) -> maturity dates or None (identities/dates only).
    label_values(record, cutoff=CUTOFF) -> same-order five-session shareholder
    returns or None. Callback must enforce supported corporate-event/PIT rules.
    Neither callback may change record constituents. No future value is requested.
    """
    frames, exclusions, seen = {b: [] for b in BASES}, [], set()
    for rec in records:
        base, day = rec["base"], pd.Timestamp(rec["signal_date"])
        require(base in BASES and START <= day < CUTOFF and (base, day) not in seen,
                "UNIQUE_BOUNDED_BASE_RECORD")
        seen.add((base, day))
        reason = rec["status"]
        if reason == "TARGET_RECORDED":
            clock = label_clock(rec)
            if clock is None:
                reason = "WHOLE_TARGET_LABEL_CLOCK_UNAVAILABLE"
            else:
                dates = pd.DatetimeIndex(clock)
                require(len(dates) == len(rec["weights"]), "LABEL_CLOCK_KEYS_MISMATCH")
                if dates.hasnans or not (dates > day).all() or not (dates < CUTOFF).all():
                    reason = "WHOLE_TARGET_LABEL_NOT_MATURE"
                else:
                    returns = label_values(rec, cutoff=CUTOFF)
                    if returns is None or not np.isfinite(np.asarray(returns, float)).all():
                        reason = "WHOLE_TARGET_SUPPORTED_LABEL_UNAVAILABLE"
                    else:
                        frames[base].append(gross.training_rows(rec["weights"],
                            rec["feature_matrix"], rec["raw_scores"], returns,
                            signal_date=day, label_mature_dates=dates, cutoff=CUTOFF))
                        continue
        exclusions.append(dict(base=base, signal_date=str(day.date()), reason=reason))
    return {b: pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=COLUMNS)
            for b, parts in frames.items()}, exclusions


def split_samples(frame):
    require(not frame.empty and set(COLUMNS) <= set(frame), "NONEMPTY_GROSS_SAMPLES")
    day, mature = pd.to_datetime(frame.signal_date), pd.to_datetime(frame.label_mature_date)
    require(not day.isna().any() and not mature.isna().any() and (day >= START).all()
            and (day < CUTOFF).all() and (mature > day).all() and (mature < CUTOFF).all(),
            "STRICT_SIGNAL_AND_LABEL_CUTOFF")
    require(frame.base_tradable_gross.gt(0).all() and frame.base_tradable_gross.le(1 + 1e-10).all()
            and frame.friction.eq(gross.FRICTION).all(), "UNCHANGED_BASE_MASS_AND_FRICTION")
    expected = gross.gross_targets(frame.basket_y.to_numpy(float),
        frame.base_tradable_gross.to_numpy(float), frame.gross_previous_proxy.to_numpy(float))
    require(np.array_equal(frame.target.to_numpy(float), expected), "ORIGINAL_GROSS_TARGET_REQUIRED")
    for _, rows in frame.groupby("signal_date", sort=True):
        require(len(rows) == len(gross.GRID)
                and np.array_equal(np.sort(rows.gross_previous_proxy), gross.GRID), "EXACT_FIVE_PRIOR_REQUESTS")
    sessions = pd.DatetimeIndex(sorted(day.unique()))
    require(len(sessions) > CAL_SESSIONS, "TRAIN_AND_60_DIAGNOSTIC_SESSIONS_REQUIRED")
    calibration = sessions[-CAL_SESSIONS:]
    train = frame.loc[(day < calibration[0]) & (mature < calibration[0])].copy()
    cal = frame.loc[day.isin(calibration)].copy()
    require(not train.empty, "PURGED_TRAIN_EMPTY")
    return train, cal, dict(calibration_start=str(calibration[0].date()),
        calibration_sessions=[str(d.date()) for d in calibration],
        train_rows=len(train), diagnostic_rows=len(cal),
        purged_rows=int(((day < calibration[0]) & ~(mature < calibration[0])).sum()),
        calibration_driven_selection=False)


def save_samples(run, frames, exclusions, source_refs):
    """Called only by the released historical bootstrap after original-engine replay."""
    paths = resolve(); run = Path(run).resolve()
    assert_safe_output_path(run, kind="backtest", paths=paths)
    require(set(frames) == set(BASES) and set(source_refs) == set(SOURCE_KEYS), "SAMPLE_SOURCE_MANIFEST_REQUIRED")
    for item in source_refs.values(): verify(item)
    out = run / "gross_samples"
    saved = out / "SAMPLE_RECEIPT.json"
    if saved.exists():
        old = document(reference(saved))
        require(old["status"] == "SAMPLES_READY" and old["source_refs"] == source_refs
                and old["history"] == history_config(), "SAMPLE_RESUME_IDENTITY_CHANGED")
        for ref in old["samples"].values(): verify(ref)
        return reference(saved)
    require(not out.exists(), "SAMPLE_CHECKPOINT_EXISTS_REUSE_EXACT_MANIFEST")
    splits = {b: split_samples(frames[b])[2] for b in BASES}
    out.mkdir()
    refs = {}
    for base in BASES:
        path = out / (base + ".parquet")
        frames[base].loc[:, list(COLUMNS)].to_parquet(path, index=False)
        refs[base] = reference(path)
    receipt = dict(status="SAMPLES_READY", history=history_config(), source_refs=source_refs,
                   samples=refs, splits=splits, exclusions=exclusions)
    write_json_atomic(out / "SAMPLE_RECEIPT.json", receipt)
    return reference(out / "SAMPLE_RECEIPT.json")


def resource_gate(resource_owner_ref):
    path = verify(resource_owner_ref)
    spec = importlib.util.spec_from_file_location("_gross_resource_owner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    memory = module.memory()
    require(memory["physical_gib"] >= 1.5 and memory["page_gib"] >= 8,
            "ORIGINAL_RESOURCE_ADMISSION")
    return memory


def verify_raw_models(refs, equivalence_ref):
    require(set(refs) == {"2023", "2024"}, "EXACT_PAST_RAW_VINTAGES")
    eq = document(equivalence_ref)
    checks = {r["year"]: r for r in eq["years"] if r["year"] in (2023, 2024)}
    require(eq["status"] == "PASS" and set(checks) == {2023, 2024}
            and all(r["equal_within_1e_minus_12"] for r in checks.values()), "RAW_EQUIVALENCE_REQUIRED")
    for year, ref in refs.items():
        receipt = document(ref); contract = receipt["contract"]
        expected = receipt["manifest_fingerprint"]
        require(expected == fingerprint({k:v for k,v in receipt.items() if k != "manifest_fingerprint"})
                and Path(ref["path"]).parent.parent == Path(equivalence_ref["path"]).parent,
                "RAW_MODEL_MANIFEST_AND_EQUIVALENCE_LINEAGE")
        require(contract["year"] == int(year) and contract["labelmax"] < year + "-01-01"
                and contract["train_end"] < year + "-01-01", "RAW_PAST_ONLY_MODEL")
        model = receipt["artifact"]
        verify(dict(path=model["path"], sha256=model["sha256"]))
    return True


def read_samples(ref, run):
    path = verify(ref)
    require(path.resolve().is_relative_to(run), "TASK_OWNED_SAMPLE_FILE_REQUIRED")
    parquet = pq.ParquetFile(path)
    for name in ("signal_date", "label_mature_date"):
        require(name in parquet.schema_arrow.names, "SAMPLE_CLOCK_COLUMN_REQUIRED")
        col = parquet.schema_arrow.names.index(name)
        for number in range(parquet.metadata.num_row_groups):
            stats = parquet.metadata.row_group(number).column(col).statistics
            require(stats is not None and stats.has_min_max and stats.null_count == 0
                    and pd.Timestamp(stats.min) >= START and pd.Timestamp(stats.max) < CUTOFF,
                    "NUMERIC_SAMPLE_READ_BOUNDARY_UNPROVEN")
    clocks = parquet.read(columns=["signal_date", "label_mature_date"]).to_pandas()
    require((clocks.label_mature_date > clocks.signal_date).all(), "LABEL_MATURITY_ORDER")
    return parquet.read(columns=list(COLUMNS)).to_pandas()


def diagnostics(model, frame):
    x, names = gross.owner.encode_features(frame, gross.FEATURES)
    require(tuple(model.features) == names, "DIAGNOSTIC_SCHEMA")
    predicted = models.predict(model, x)["gross"]
    utilities = gross.gross_utilities(frame.basket_y, frame.base_tradable_gross,
                                     frame.gross_previous_proxy)
    indices = np.asarray([np.flatnonzero(gross.GRID == p)[0] for p in predicted])
    chosen = utilities[np.arange(len(frame)), indices]
    metrics = pd.DataFrame(dict(signal_date=frame.signal_date.to_numpy(),
        regret=utilities.max(axis=1) - chosen,
        gain_vs_1=chosen - utilities[:, -1], gain_vs_half=chosen - utilities[:, 2]))
    return dict(metrics.groupby("signal_date").mean().mean(),
                diagnostic_only=True, calibration_fit_count=0, model_selection=False,
                account_reward_or_nav_claim=False)


def fit_slot(run, base, learner, train, cal, split, identity, dependencies):
    slot = run / "gross_models" / (base + "__" + learner)
    receipt_path = slot / "fit_receipt.json"
    tuple_sha = fingerprint(dict(identity=identity, base=base, learner=learner, split=split,
                                specification=models.specifications()))
    log = run / "GROSS_FIT_LOG.jsonl"
    previous = None
    if receipt_path.exists():
        receipt = document(reference(receipt_path))
        previous = receipt.copy()
        require(receipt["tuple_sha256"] == tuple_sha, "GROSS_RESUME_IDENTITY_CHANGED")
        if receipt["status"] == "TRAINED":
            path = verify(receipt["model_ref"])
            if "diagnostic" not in receipt:
                receipt["diagnostic"] = diagnostics(joblib.load(path), cal)
                write_json_atomic(receipt_path, receipt)
            return receipt
        started = [e for e in values._events(log) if e.get("event") == "FIT_STARTED"
                   and e.get("reuse_tuple_sha256") == tuple_sha]
        require(receipt.get("fit_units", 0) == 0 and not started, "FAILED_STARTED_FIT_MUST_NOT_REFIT")
    slot.mkdir(parents=True, exist_ok=True)
    receipt = dict(status="VALIDATING", base=base, learner=learner, tuple_sha256=tuple_sha,
                   fit_units=0, receipt_path=str(receipt_path), split=split,
                   previous_zero_fit_attempt=previous)
    write_json_atomic(receipt_path, receipt)
    try:
        x, names = gross.owner.encode_features(train, gross.FEATURES)
        target = dict(objective="gross", learner=learner, target=train.target.to_numpy(float),
            sample_weight=gross.owner.date_weights(train.signal_date),
            source_sha256=models.source_sha256(), seed=models.SEED)
        model = values._fit_job("decision", base + "__" + learner, x, target,
            train.signal_date.to_numpy(), None, dependencies, names, None,
            log=log, auth=dict(max_fit_units=FIT_CAP, max_new_bucket_fit_units=FIT_CAP,
                              budget_bucket=TASK + "_GROSS"), prior=0, year=2024,
            tuple_sha=tuple_sha, receipt=receipt, worker_target=models.worker)
        expected = models.specifications()["fit_units"]["classification"][learner]
        require(receipt["fit_units"] == expected, "ACTUAL_COMPONENT_FIT_COUNT")
        path = slot / "model.joblib"
        with path.open("xb") as stream: joblib.dump(model, stream, compress=3)
        receipt.update(status="TRAINED", model_ref=reference(path), model_metadata=model.metadata)
        write_json_atomic(receipt_path, receipt)
    except BaseException as exc:
        receipt.update(status="FAILED", error=type(exc).__name__ + ":" + str(exc))
        write_json_atomic(receipt_path, receipt)
        raise
    # Persist the completed estimator before diagnostics; a diagnostic failure
    # resumes only diagnostics and never repeats physical fitting.
    receipt["diagnostic"] = diagnostics(model, cal)
    write_json_atomic(receipt_path, receipt)
    return receipt


def run_training(manifest_ref):
    manifest = document(manifest_ref)
    require(manifest["task_id"] == TASK and manifest["permits"].get("train") is True,
            "SOURCE_RELEASE_BEFORE_NUMERIC_READ_OR_FIT")
    require(manifest["driver_ref"] == reference(__file__) and manifest["history"] == history_config(),
            "FROZEN_DRIVER_AND_HISTORY_REQUIRED")
    require(manifest["runtime_source_refs"] == runtime_source_refs(), "FROZEN_TRAINING_OWNER_PINS")
    run = Path(manifest["run_root"]).resolve()
    assert_safe_output_path(run, kind="backtest", paths=resolve())
    require(run.is_dir() and (run / "run_config.json").is_file(), "EXISTING_TASK_RUN_REQUIRED")
    sample_receipt = document(manifest["sample_receipt_ref"])
    require(sample_receipt["status"] == "SAMPLES_READY" and sample_receipt["history"] == history_config()
            and set(sample_receipt["source_refs"]) == set(SOURCE_KEYS), "QUALIFIED_HISTORICAL_SAMPLE_RECEIPT")
    for ref in sample_receipt["source_refs"].values(): verify(ref)
    contract = document(sample_receipt["source_refs"]["contract"])
    require(contract["research_id"] == TASK and tuple(contract["bases"]) == BASES
            and tuple(contract["learners"]) == models.LEARNERS
            and contract["controller_signal_and_label_maturity_cutoff_exclusive"] == str(CUTOFF.date())
            and contract["fit_budget"]["gross_physical_fit_cap"] == FIT_CAP
            and tuple(contract["ordered_features"]) == gross.FEATURES, "FIXED_GROSS_CONTRACT")
    verify_raw_models(manifest["raw_model_manifest_refs"], sample_receipt["source_refs"]["raw_equivalence"])
    dependencies = tuple(manifest.get("dependencies", []))
    with continuation_lock(run, manifest["driver_ref"]["sha256"], namespace=TASK + "_GROSS"):
        bundle = run / "GROSS_MODEL_BUNDLE.json"
        if bundle.exists():
            old = document(reference(bundle))
            require(old["manifest_ref"] == manifest_ref, "GROSS_BUNDLE_IDENTITY_CHANGED")
            if old["status"] == "SIX_GROSS_MODELS_TRAINED":
                require(len(old["models"]) == 6, "SIX_COMPLETED_MODEL_CHECKPOINTS")
                for item in old["models"]: verify(item["model_ref"])
                return old
        # Admission happens before numeric reads or trial receipts; low RAM is not a failed trial.
        resource_gate(manifest["resource_owner_ref"])
        completed = []
        for base in BASES:
            frame = read_samples(sample_receipt["samples"][base], run)
            train, cal, split = split_samples(frame)
            require(split == sample_receipt["splits"][base], "SAMPLE_SPLIT_CHANGED")
            for learner in models.LEARNERS:
                resource_gate(manifest["resource_owner_ref"])
                try:
                    completed.append(fit_slot(run, base, learner, train, cal, split,
                                               manifest_ref, dependencies))
                except Exception as exc:
                    completed.append(dict(base=base, learner=learner,
                        status="FAILED_OR_DIAGNOSTIC_PENDING_NO_AUTOMATIC_REFIT",
                        error=type(exc).__name__ + ":" + str(exc)))
            # Release this base before reading the next base; diagnostics are already materialized.
            del frame, train, cal
            import gc
            gc.collect()
        status = ("SIX_GROSS_MODELS_TRAINED" if all(r["status"] == "TRAINED" for r in completed)
                  else "SIX_FIXED_ARMS_ATTEMPTED_WITH_PRESERVED_FAILURES")
        result = dict(status=status, manifest_ref=manifest_ref,
                      models=completed, fit_cap=FIT_CAP, test_rows_read=0)
        write_json_atomic(run / "GROSS_MODEL_BUNDLE.json", result)
        return result


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--stage", choices=("metadata", "train"), default="metadata")
    args = parser.parse_args(argv)
    ref = dict(path=str(Path(args.manifest).resolve()), sha256=args.sha256)
    if args.stage == "metadata":
        meta = document(ref)
        print(json.dumps(dict(task_id=meta["task_id"], permits=meta["permits"],
                              history=history_config(), numeric_reads=0, fits=0)))
    else:
        result = run_training(ref)
        print(json.dumps(dict(status=result["status"], models=len(result["models"]))))


if __name__ == "__main__":
    main()
