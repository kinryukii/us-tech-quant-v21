"""R5 metadata-only completion on exact active membership intervals.

Reuses canonical parquet custody guards and storage routing. This is not a
security master: intervals certify membership only inside their frozen bounds.
No prediction/target/price values, model loading, fitting or provider calls.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.data.joint_input_binding import guard_parquet, sha256
from scripts.research.a2.evaluation.joint_frozen_history_risk_r3 import write, read_json
from scripts.research.a2.evaluation import joint_frozen_history_risk_bank_r3 as scanner

REPO = Path(__file__).resolve().parents[4]
ID = "V24_B_DYNAMIC_FULLPOOL_RISK_AND_IDENTITY_R5"
PARENT = Path("D:/us-tech-quant-backtests/V24/20261003T181407+0000_ddb7b537")
PIT = Path("D:/us-tech-quant-results/A2_PIT13F_MATERIALIZATION_R1")
BOUNDARY = pd.Timestamp("2026-01-01")
KEYS = ["signal_date", "ticker"]
IDENTITY = ["security_id", "security_id_type", "cusip", "active_13f_quarter", "quarter_universe_fingerprint"]
SECURITY = IDENTITY[:3]
HELD_PINS = {
  2022:"312bc71eaa6388a97901d452e6f0c2b0f331a9a873bd0c7616db0e02c902457f",
  2023:"8ef56a62072eb444e0d6f574d939ada02ab42d2d8015e7968255a0430ddc227d",
  2024:"cfa0d809e5c2c4ed409e67f29caa80e45439b4fad2afcf6631e384af55719e6a",
  2025:"04129a6c553f06bcbdd58b966f05f0df9fff6003168fe0f9832301676fb66658"}
SOURCE_PINS = {
 "intervals":(PIT/"effective_universe_intervals.parquet","cafd53e665143e56d31c3f7b5299593a099fc53a0032879d63fbd8abae6a0d30"),
 "quarters":(PIT/"quarterly_universe.parquet","097f616fbd68d01891427fc7d8e06607c2284b36e9b046df84f0ceb63bd4cfbb"),
 "rule":(PIT/"pit13f_rule_manifest.json","3bcd10749d9b182dc27c0c51fccf1562437087ea27055e053ba059bdea493e07"),
 "manifest":(PIT/"source_hash_manifest.json","d9f3032b4c154ebd62e88291a36e6a4f1d2d1680b6f3d95ccc4675813afcfd73")}
LEGACY_EXPECTED_MANIFEST = "d9f303b9e7741083207567bc1bddf9d5efc5b181a9a11eeae504c5d68521796f"
PRODUCER_PINS = {
 "freeze":("D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1/audit/freeze_r1/frozen_baseline_manifest.json","398cff8076f8c761d87c12ce195ba98e9201209499caaaf7a14ae05ac1605125"),
 "producer":("D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1/scripts/run_rebuild.py","68f4eb6599638db4c6af51b0ff8894f757b78a60dba27ce03e5c798e9508cc0e"),
 "integrity":("D:/us-tech-quant-results/13f_pit_v1/scripts/v17b/integrity_rebuild_v17b.py","df9a31733b14f5cec03924c5a59708cc7dfa1fa6c305b2f17292475efbb5a89d")}


def _dates(s):
    result = pd.to_datetime(s, errors="raise")
    if result.dt.tz is not None or result.isna().any() or result.ge(BOUNDARY).any():
        raise ValueError("PRE2026_NAIVE_SESSION_DATE_REQUIRED")
    if not result.eq(result.dt.normalize()).all():
        raise ValueError("EXACT_SESSION_DATE_REQUIRED")
    return result


def _valid(s):
    text = s.astype("string").str.strip()
    return (text.notna() & text.ne("") & ~text.str.upper().str.startswith(("UNKNOWN", "HELD_", "TICKER_"))).fillna(False)


def _metadata_projection(path, root_fields):
    # The existing fixed-writer scanner skips disallowed values before decoding.
    old = scanner._fixed_field
    def field(p, key, profile):
        if not p:
            return key in root_fields
        return key not in {"notes", "error", "metrics", "outcomes", "values", "predictions", "y_open5"}
    scanner._fixed_field = field
    try:
        with Path(path).open("r", encoding="utf-8-sig") as f:
            lines = (line if line.endswith("\n") else line+"\n" for line in iter(f.readline, ""))
            return scanner._FixedProducerProjection(lines, "ledger", 65536).parse()
    finally:
        scanner._fixed_field = old


def _pin(path, digest):
    path = Path(path)
    if path.drive.upper() in {"E:", "F:"} or sha256(path) != digest:
        raise ValueError("SOURCE_CUSTODY_PIN_MISMATCH")
    return {"path":str(path), "sha256":digest, "bytes":path.stat().st_size}


def qualify_identity(held, intervals, quarters, *, source_qualified):
    """Preserve all keys/order. No nearest/asof fill across an interval gap."""
    if set(held) != set(KEYS+IDENTITY):
        raise ValueError("IDENTITY_METADATA_PROJECTION_ONLY")
    held = held.copy().reset_index(drop=True)
    held.signal_date = _dates(held.signal_date)
    if not _valid(held.ticker).all() or held.duplicated(KEYS).any():
        raise ValueError("UNIQUE_UNCHANGED_HELD_KEYS_REQUIRED")
    intervals = intervals.copy()
    for c in ("effective_start", "effective_end"):
        intervals[c] = _dates(intervals[c])
    if intervals.effective_end.lt(intervals.effective_start).any():
        raise ValueError("INVALID_IDENTITY_INTERVAL")
    quarters = quarters.copy()
    for c in ("effective_date", "effective_end"):
        quarters[c] = _dates(quarters[c])
    if quarters.effective_end.lt(quarters.effective_date).any():
        raise ValueError("INVALID_QUARTER_INTERVAL")
    out = held[KEYS].copy()
    out["parent_row_ordinal"] = np.arange(len(out), dtype=np.int64)
    for c in IDENTITY:
        out["original_"+c] = held[c]
        out[c] = pd.Series(pd.NA, index=out.index, dtype="string")
    count = np.zeros(len(out), dtype=np.int16)
    incomplete = np.zeros(len(out), dtype=bool)
    candidate = pd.DataFrame(pd.NA, index=out.index, columns=IDENTITY, dtype="string")
    groups = {}
    for ticker, index in held.groupby("ticker", sort=False).groups.items():
        positions = np.asarray(index, dtype=np.int64)
        order = np.argsort(held.loc[positions,"signal_date"].to_numpy(), kind="stable")
        positions = positions[order]
        groups[ticker] = (positions, held.loc[positions,"signal_date"].to_numpy())
    for row in intervals.itertuples(index=False):
        if row.ticker not in groups:
            continue
        positions, dates = groups[row.ticker]
        lo = dates.searchsorted(row.effective_start.to_datetime64(), side="left")
        hi = dates.searchsorted(row.effective_end.to_datetime64(), side="right")
        index = positions[lo:hi]
        if not len(index):
            continue
        count[index] += 1
        values = [row.security_id, row.security_id_type, row.cusip,
                  row.report_quarter, row.quarter_universe_fingerprint]
        valid = bool(_valid(pd.Series(values)).all() and row.mapping_status == "RESOLVED"
                     and row.security_id_type == "CUSIP" and row.security_id == row.cusip)
        incomplete[index] |= not valid
        for c, value in zip(IDENTITY, values):
            candidate.loc[index, c] = value if valid else pd.NA
    state_count = np.zeros(len(out), dtype=np.int16)
    state = pd.DataFrame(pd.NA, index=out.index, columns=IDENTITY[3:], dtype="string")
    for row in quarters.itertuples(index=False):
        index = np.flatnonzero(held.signal_date.between(row.effective_date, row.effective_end).to_numpy())
        state_count[index] += 1
        if _valid(pd.Series([row.report_quarter, row.universe_fingerprint])).all():
            state.loc[index, IDENTITY[3:]] = [row.report_quarter, row.universe_fingerprint]
    state_ok = (state_count == 1) & state.notna().all(axis=1).to_numpy()
    conflict = np.zeros(len(out), dtype=bool)
    unique = (count == 1) & ~incomplete
    for c in IDENTITY:
        proposed = candidate[c] if c in SECURITY else state[c]
        defined = unique if c in SECURITY else state_ok
        conflict |= (_valid(held[c]).to_numpy() & defined & held[c].astype("string").ne(proposed).fillna(False).to_numpy())
    for c in IDENTITY[3:]:
        conflict |= (unique & state_ok & candidate[c].ne(state[c]).fillna(True).to_numpy())
    qualified = unique & state_ok & ~conflict & bool(source_qualified)
    out["active_membership_interval_count"] = count
    out["active_global_quarter_count"] = state_count
    out["quarter_state_qualified"] = state_ok & bool(source_qualified)
    out["original_identity_conflict"] = conflict
    out["identity_qualified"] = qualified
    out["reason"] = "QUALIFIED_EXACT_ACTIVE_MEMBERSHIP_SOURCE"
    if not source_qualified:
        out["reason"] = "SOURCE_AUTHORITY_UNQUALIFIED"
    if source_qualified:
        out.loc[count == 0,"reason"] = "NO_LEGAL_ASOF_SECURITY_INTERVAL"
        out.loc[incomplete & (count == 1),"reason"] = "INCOMPLETE_IDENTITY_SOURCE"
        out.loc[count > 1,"reason"] = "AMBIGUOUS_ACTIVE_SECURITY_INTERVAL"
        out.loc[~state_ok,"reason"] = "NO_UNIQUE_ACTIVE_QUARTER_STATE"
        out.loc[conflict,"reason"] = "ORIGINAL_IDENTITY_CONFLICT"
    for c in SECURITY:
        out.loc[qualified,c] = candidate.loc[qualified,c]
    for c in IDENTITY[3:]:
        out.loc[out.quarter_state_qualified,c] = state.loc[out.quarter_state_qualified,c]
    if len(out) != len(held) or not out[KEYS].equals(held[KEYS]):
        raise ValueError("FULL_HELD_DOMAIN_CHANGED")
    return out


def source_authority():
    pins = {name:_pin(*pin) for name,pin in {**SOURCE_PINS,**PRODUCER_PINS}.items()}
    manifest = _metadata_projection(SOURCE_PINS["manifest"][0], {
        "existing_package_hash_verified","frozen_hash_match_count","frozen_hash_mismatch_count","outputs","run_id"})
    # This physically pinned rule is entirely source/governance metadata, has
    # no outcomes/labels, and its producer uses an inline dedup-key array. The
    # canonical JSON reader is appropriate; mixed manifest uses scanner above.
    rule = read_json(SOURCE_PINS["rule"][0])
    outputs = {Path(x["path"]).name:x["sha256"] for x in manifest["outputs"]}
    consistent = (manifest["existing_package_hash_verified"] is True
        and manifest["frozen_hash_match_count"] == 46 and manifest["frozen_hash_mismatch_count"] == 0
        and rule["research_cutoff_exclusive"] == "2026-01-01"
        and rule["authoritative_rules_verified"] is True and rule["rule_discrepancy_count"] == 0)
    for name in ("intervals","quarters","rule"):
        consistent &= outputs.get(SOURCE_PINS[name][0].name) == SOURCE_PINS[name][1]
    for name, field in (("freeze","authoritative_freeze_manifest"),("producer","authoritative_rebuild_source"),
                        ("integrity","upstream_integrity_source")):
        consistent &= rule[field]["sha256"] == PRODUCER_PINS[name][1] and Path(rule[field]["path"]) == Path(PRODUCER_PINS[name][0])
    if not consistent:
        raise ValueError("CURRENT_ARCHIVE_INTERNAL_AUTHORITY_CONFLICT")
    return {"schema":"R5_CURRENT_ARCHIVE_MEMBERSHIP_IDENTITY_AUTHORITY",
        "source_qualified_for":"PRE2026_FROZEN_HISTORY_EXACT_MEMBERSHIP_MECHANISM_ONLY",
        "current_source_internally_pinned":True,"pins":pins,"rule":rule,
        "legacy_manifest_custody_conflict":{"expected":LEGACY_EXPECTED_MANIFEST,
            "actual":SOURCE_PINS["manifest"][1],"closed":False,"parent_qualification_restored":False},
        "security_lifespan_claim":False,"cross_interval_carry_allowed":False,
        "historical_quote_authority_status":"UNKNOWN","strict_PIT_promotion_eligible":False,
        "quote_qualified":False,"certified_nav_qualified":False,"read_2026":False,"provider_fetches":0}


def _summary(frame):
    counts = {c:int((~_valid(frame["original_"+c])).sum()) for c in IDENTITY}
    return {"rows":len(frame),"original_missing_by_field":counts,
        "qualified":int(frame.identity_qualified.sum()),"unqualified":int((~frame.identity_qualified).sum()),
        "global_quarter_state_qualified":int(frame.quarter_state_qualified.sum()),
        "original_identity_conflicts":int(frame.original_identity_conflict.sum()),
        "reasons":{str(k):int(v) for k,v in frame.reason.value_counts().items()},
        "distinct_tickers":int(frame.ticker.nunique()),"rows_dropped":0,"rows_reordered":0}


def execute(run):
    run = Path(run).resolve()
    paths = resolve(REPO)
    assert_safe_output_path(run/"identity", kind="backtest", paths=paths)
    cfg = json.loads((run/"run_config.json").read_text(encoding="utf-8"))
    if cfg.get("task_id") != ID or Path(cfg.get("parent_run","")).resolve() != PARENT.resolve():
        raise ValueError("R5_PARENT_RUN_IDENTITY_REQUIRED")
    if (run/"identity/IDENTITY_COMPLETION_RECEIPT_R5.json").exists():
        raise ValueError("IMMUTABLE_COMPLETION_ALREADY_EXISTS")
    authority = source_authority()
    write(run,"identity/IDENTITY_SOURCE_AUTHORITY_R5.json",authority)
    _, interval_guard = guard_parquet(*SOURCE_PINS["intervals"],["effective_start","effective_end"])
    _, quarter_guard = guard_parquet(*SOURCE_PINS["quarters"],["effective_date","effective_end"])
    interval_dataset = ds.dataset(SOURCE_PINS["intervals"][0],format="parquet")
    quarter_dataset = ds.dataset(SOURCE_PINS["quarters"][0],format="parquet")
    result = {"schema":"R5_FULL_UNCHANGED_HELD_IDENTITY_COMPLETION_RECEIPT","research_id":ID,
        "parent_run":str(PARENT),"source_authority_ref":{"path":str(run/"identity/IDENTITY_SOURCE_AUTHORITY_R5.json"),
            "sha256":sha256(run/"identity/IDENTITY_SOURCE_AUTHORITY_R5.json")},
        "source_guards":{"intervals":interval_guard,"quarters":quarter_guard},"annual":{},
        "fit_attempts":0,"opportunity_value_columns_read":[],"labels_read":0,"economic_outcomes_read":0,
        "provider_fetches":0,"test2026_rows_read":0,"parent_artifacts_modified":False,
        "strict_PIT_promotion_eligible":False,"quote_qualified":False,"certified_nav_qualified":False,
        "code_ref":{"path":str(Path(__file__)),"sha256":sha256(__file__)}}
    for year,digest in HELD_PINS.items():
        path = PARENT/f"OOF/OPPORTUNITY_ridge_{year}.parquet"
        file, proof = guard_parquet(path,digest,["signal_date","source_fit_cutoff","source_label_mature_max"])
        held = file.read(columns=KEYS+IDENTITY).to_pandas()
        if not pd.to_datetime(held.signal_date).dt.year.eq(year).all():
            raise ValueError("ANNUAL_HELD_METADATA_DOMAIN_CONFLICT")
        start,stop=f"{year}-01-01",f"{year+1}-01-01"
        def scalar(dataset,field,value):
            dtype=dataset.schema.field(field).type
            value=value if pa.types.is_string(dtype) else (pd.Timestamp(value).date() if pa.types.is_date(dtype) else pd.Timestamp(value).to_pydatetime())
            return pa.scalar(value,type=dtype)
        ip=(ds.field("effective_start") < scalar(interval_dataset,"effective_start",stop)) & (ds.field("effective_end") >= scalar(interval_dataset,"effective_end",start))
        qp=(ds.field("effective_date") < scalar(quarter_dataset,"effective_date",stop)) & (ds.field("effective_end") >= scalar(quarter_dataset,"effective_end",start))
        intervals=interval_dataset.to_table(columns=["ticker","effective_start","effective_end","report_quarter",*SECURITY,"quarter_universe_fingerprint","mapping_status"],filter=ip).to_pandas()
        quarters=quarter_dataset.to_table(columns=["report_quarter","effective_date","effective_end","universe_fingerprint"],filter=qp).to_pandas()
        output = qualify_identity(held,intervals,quarters,source_qualified=True)
        target = run/f"identity/HELD_IDENTITY_QUALIFICATION_{year}.parquet"
        assert_safe_output_path(target,kind="backtest",paths=paths)
        if target.exists():
            raise ValueError("IMMUTABLE_IDENTITY_DIAGNOSTIC_EXISTS")
        output.to_parquet(target,index=False)
        summary = _summary(output)
        summary.update(parent_source_guard=proof,projection_columns=KEYS+IDENTITY,
            identity_source_projection={"year":year,"predicate":"effective_start/date < annual_stop AND effective_end >= annual_start; exact signal-date inside interval", "interval_rows":len(intervals),"quarter_rows":len(quarters)},
            diagnostic_ref={"path":str(target),"sha256":sha256(target)},
            consumer_publish_eligible=summary["unqualified"] == 0,
            field_semantics={"security_id/type/cusip":"exact ticker/date active membership interval; no lifespan extension",
                "active_13f_quarter/fingerprint":"independent date-level active universe state, including nonmembers"})
        result["annual"][str(year)] = summary
        print(json.dumps({"year":year,"rows":summary["rows"],"qualified":summary["qualified"],"reasons":summary["reasons"]}),flush=True)
    result["total_rows"] = sum(x["rows"] for x in result["annual"].values())
    result["qualified_rows"] = sum(x["qualified"] for x in result["annual"].values())
    result["unqualified_rows"] = result["total_rows"]-result["qualified_rows"]
    result["full_unchanged_held_identity_qualified"] = result["unqualified_rows"] == 0
    result["terminal_status"] = "QUALIFIED_FULL_UNCHANGED_HELD_IDENTITY" if result["full_unchanged_held_identity_qualified"] else "FULL_HELD_IDENTITY_UNRESOLVED_NO_LEGAL_ASOF_MASTER"
    result["consumer_sidecar_published"] = result["full_unchanged_held_identity_qualified"]
    result["remaining_required_object"] = None if result["full_unchanged_held_identity_qualified"] else "Historical date-asof security identity authority for every retained key outside exact qualified membership intervals, plus explicit conflict resolution; no future mapping or carry substitution."
    write(run,"identity/IDENTITY_COMPLETION_RECEIPT_R5.json",result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run",required=True)
    args = parser.parse_args()
    result = execute(args.run)
    print(json.dumps({"terminal_status":result["terminal_status"],"total_rows":result["total_rows"],
        "qualified_rows":result["qualified_rows"],"unqualified_rows":result["unqualified_rows"]}),flush=True)

if __name__ == "__main__":
    main()
