"""Task-only historical application; bootstrap precedes every financial import.

No source acquisition, fit, account, or financial read occurs on import. Prepare
and account are separately released to allow typed-event authority sealing.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import FunctionType

TASK = "A_BASE_CONDITIONED_GROSS_6_COMBINATIONS_20261013_R1"
FIRST = "2023-01-03"
START = "2024-01-02"
CUTOFF = "2024-10-07"
BASES = ("R10_DIRECT_MEAN4_ELASTICNET_MID", "R10_DIRECT_H5_RIDGE_MID")
TASK_RAW_FEATURE_TAG = "REBUILT_ORIGINAL_RAW_FORWARD32_BOUNDED_TASK_SOURCE_DRAFT"
KNOWN_TASK_RAW_FEATURE_TAGS = (
    TASK_RAW_FEATURE_TAG,
    "REBUILT_ORIGINAL_NATIVE_RAW_FORWARD32_BOUNDED_TASK_SOURCE_DRAFT",
    "REBUILT_ORIGINAL_FROZEN_RAW_FORWARD_SURFACE32_BOUNDED_TASK_SOURCE_DRAFT",
    "REBUILT_ORIGINAL_NATIVE_RAW_FORWARD32_HISTORICAL_TRANSPORT_PROOF_DRAFT",
    "REBUILT_ORIGINAL_NATIVE_RAW_FORWARD32_PROCESS_DATE_GATE_TASK_SOURCE_DRAFT",
    "REBUILT_ORIGINAL_NATIVE_FORWARD32_TIINGO_RAW_UNIT_QUALIFIED_TASK_SOURCE_DRAFT",
)


def need(ok, reason):
    if not ok: raise ValueError(reason)


def ref(path):
    p = Path(path).resolve()
    with p.open("rb") as f: digest = hashlib.file_digest(f, "sha256").hexdigest()
    return {"path": str(p), "sha256": digest}


def verify(record):
    need(ref(record["path"]) == record, "HISTORY_SOURCE_PIN_CHANGED")
    return Path(record["path"])


def doc(record, limit=250000):
    p = Path(record["path"])
    need(p.stat().st_size <= limit, "HISTORY_METADATA_LIMIT")
    verify(record)
    return json.loads(p.read_text(encoding="utf-8-sig"))


def module(record, name):
    path = verify(record)
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def bounded_static_records(path, cutoff=CUTOFF):
    """Exact known source layout: event_date first; rejected dicts never eval.

    Only the original pure fingerprint helpers and selected literal dictionaries
    are evaluated. Original future dictionaries never enter ast.literal_eval.
    """
    need(cutoff == CUTOFF, "FIXED_STATIC_BOUNDARY")
    header, records, dates, selected, state, block = [], [], [], [], "header", None
    with Path(path).open(encoding="utf-8-sig") as stream:
        for line in stream:
            if state == "header":
                if line.startswith("def frozen_evidence_records("):
                    state = "seek"
                else: header.append(line)
            elif state == "seek":
                if line.strip() == "records = [": state = "records"
            elif state == "records":
                if line == "    ]\n": break
                need(line == "        {\n", "STATIC_FLAT_RECORD_START")
                prefix = next(stream)
                match = re.match(r'\s*"ticker": "[^"\n]+", "event_date": "(\d{4}-\d{2}-\d{2})",', prefix)
                need(match is not None, "STATIC_DATE_MUST_PRECEDE_PAYLOAD")
                day = match.group(1); dates.append(day)
                keep = day < cutoff
                block = ["{\n", prefix] if keep else None
                for line in stream:
                    if line == "        },\n":
                        if keep: block.append("}\n")
                        break
                    need(line.startswith("            "), "STATIC_FLAT_RECORD_LAYOUT")
                    if keep: block.append(line)
                else: raise ValueError("STATIC_RECORD_UNTERMINATED")
                if keep:
                    record = ast.literal_eval("".join(block))
                    need(record["event_date"] == day, "STATIC_DATE_CHANGED")
                    records.append(record); selected.append(day)
        else: raise ValueError("STATIC_RECORDS_END_MISSING")
    helpers = ast.parse("".join(header))
    nodes = [n for n in helpers.body if isinstance(n, ast.FunctionDef)
             and n.name in {"canonical_bytes", "payload_sha256"}]
    need(len(nodes) == 2 and bool(dates), "ORIGINAL_STATIC_FINGERPRINT_OWNER")
    ns = {"json": json, "hashlib": hashlib, "Any": object}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(path), "exec"), ns)
    for record in records:
        record["source_fingerprint"] = ns["payload_sha256"](
            {k:v for k,v in record.items() if k != "source_fingerprint"})
    # The unchanged frozen_events function compiles this bounded supplier only.
    source = "def frozen_evidence_records():\n    return " + repr(records) + "\n"
    return records, source, dict(all_event_dates=dates, selected_event_dates=selected,
                                excluded_payloads_evaluated=0)


def bounded(record, columns, date_column, first=FIRST, *, second_clock=None, extra=None):
    import pandas as pd
    import pyarrow.dataset as ds
    path = verify(record)
    source = ds.dataset(path, format="parquet")
    need(set(columns) <= set(source.schema.names), "BOUNDED_SOURCE_SCHEMA")
    import pyarrow as pa
    def clock(value, column):
        kind = source.schema.field(column).type
        if pa.types.is_string(kind) or pa.types.is_large_string(kind): return str(pd.Timestamp(value).date())
        if pa.types.is_date(kind): return pd.Timestamp(value).date()
        return pd.Timestamp(value).to_pydatetime()
    rule = ((ds.field(date_column) >= clock(first,date_column))
            & (ds.field(date_column) < clock(CUTOFF,date_column)))
    if second_clock:
        rule &= ds.field(second_clock).is_null() | (ds.field(second_clock) < clock(CUTOFF,second_clock))
    if extra is not None: rule &= extra
    parts, count = [], 0
    for batch in source.scanner(columns=list(columns), filter=rule, batch_size=4096, use_threads=False).to_batches():
        count += batch.num_rows; need(count <= 600000, "BOUNDED_HISTORY_ROW_CAP")
        parts.append(batch.to_pandas())
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=columns)


def typed_events(sources):
    """Retain original classification CodeType; replace only scoped suppliers."""
    import pandas as pd
    from dataclasses import asdict
    from scripts.common.json_projection import metadata_fields
    old = module(sources["account_source"], "_gross_history_original_account")
    projection_path = verify(sources["bounded_event_binding"])
    with projection_path.open("rb") as f:
        meta = metadata_fields(f, {"schema", "cutoff_exclusive", "static_source_path",
                                  "static_source_sha256", "source_path", "source_sha256"})
    need(meta["schema"] == "BOUNDED_R10_EVENT_BINDING_R1" and meta["cutoff_exclusive"] == CUTOFF,
         "REUSE_BOUNDED_EVENT_PROOF")
    static_ref = {"path": meta["static_source_path"], "sha256": meta["static_source_sha256"]}
    static_path = verify(static_ref)
    _, supplier, clock_audit = bounded_static_records(static_path)
    class SourcePath(type(Path())):
        def read_text(self, *a, **kw):
            if self.resolve() == static_path.resolve(): return supplier
            raise ValueError("UNBOUND_ORIGINAL_EVENT_SOURCE_READ")
    expected_audit = {"path": meta["source_path"], "sha256": meta["source_sha256"]}
    def read_artifact(record, columns, date_column):
        need(record == expected_audit and date_column == "event_date", "EXACT_ORIGINAL_EVENT_AUDIT")
        # Keys/clocks precede factor fields; both effective/source clocks are bounded.
        bounded(record, ["ticker", "event_date", "source_event_date"], date_column,
                first="1900-01-01", second_clock="source_event_date")
        return bounded(record, columns, date_column, first="1900-01-01", second_clock="source_event_date")
    fn = FunctionType(old.frozen_events.__code__,
        {**old.frozen_events.__globals__, "Path": SourcePath, "read_artifact": read_artifact,
         "BOUNDARY": pd.Timestamp(CUTOFF)}, old.frozen_events.__name__)
    events, known, unsupported, receipt = fn({"corporate_events": {
        "source_path": str(static_path), "source_sha256": static_ref["sha256"]}})
    projection = doc(sources["bounded_event_binding"], limit=2_000_000)
    need(receipt["event_records"] == projection["event_records"], "ORIGINAL_EVENT_RETENTION_EXACT_MATCH")
    output = dict(status="EXACT_ORIGINAL_BOUNDED_TYPED_EVENT_RETENTION", cutoff_exclusive=CUTOFF,
        source_refs={k:sources[k] for k in ("account_source", "bounded_event_binding")},
        static_ref=static_ref, original_audit_ref=expected_audit, static_clock_audit=clock_audit,
        original_classification_code_unchanged=True, event_records_exact_match=True,
        corporate_actions=[asdict(e) for e in events],
        corporate_action_known_at={k:str(v) for k,v in known.items()}, unsupported_events=unsupported)
    return events, known, unsupported, output, projection


def rank_history(features, identities, pool, calendar, raw_models, institution_count, context_identity=None, source_exclusion_keys=()):
    """Keep nominal100; explicitly authorized missing sources may stay unscored."""
    import numpy as np
    import pandas as pd
    from scripts.research.a2.inference import historical_top40 as ranking, stateful_test_inputs as flag_owner
    from scripts.research.a2.training.stateful_inputs import FEATURES
    need(not identities.duplicated(["signal_date", "cusip"]).any(), "UNIQUE_DATED_CUSIP_IDENTITY")
    f = features.rename(columns={"signal_date":"trade_date"}).copy()
    omitted = identities.loc[[
        (pd.Timestamp(d), str(c)) in source_exclusion_keys
        for d,c in identities[["signal_date","cusip"]].itertuples(index=False,name=None)],
        ["signal_date","ticker"]]
    omitted_keys = set(omitted.itertuples(index=False,name=None))
    f = f.loc[[(pd.Timestamp(d),str(t)) not in omitted_keys
               for d,t in f[["trade_date","ticker"]].itertuples(index=False,name=None)]].copy()
    finite = np.isfinite(f[list(FEATURES)].to_numpy(float)).all(axis=1)
    f = f.loc[finite].copy()
    available = set(zip(pd.to_datetime(f.trade_date), f.ticker.astype(str)))
    schedules, members, ledger, qualifications = [], [], [], []
    max_keys = set()
    for day in calendar:
        rows = pool.loc[pd.to_datetime(pool.signal_date).eq(day)].copy()
        reason = "SOURCE_UNQUALIFIED_NO_HISTORICAL_POOL"
        if len(rows):
            need(len(rows) == 100 and sorted(rows.consensus_rank.tolist()) == list(range(1,101)),
                 "EXACT_CONSENSUS100_MEMBERS_BEFORE_COVERAGE")
            identity_columns = [c for c in ("cusip","ticker","security_id","feature_available",
                                "feature_source","feature_ineligible_qualified") if c in identities]
            joined = rows.merge(identities.loc[identities.signal_date.eq(day),identity_columns],
                                on="cusip",how="left",validate="one_to_one")
            clocks = pd.to_datetime(joined.source_effective_at, utc=True)
            need(clocks.notna().all() and (clocks <= day.tz_localize("America/New_York")
                 + pd.Timedelta(hours=16)).all(), "POOL_MUST_BE_EFFECTIVE_AT_SIGNAL_CLOSE")
            eligible, excluded, task_excluded = pool_source_masks(joined.assign(signal_date=day), source_exclusion_keys)
            ready = (joined.ticker.notna().all() and joined.security_id.notna().all()
                     and not joined.ticker.duplicated().any() and (eligible | excluded | task_excluded).all()
                     and int(eligible.sum()) >= 20
                     and all((day,str(t)) in available for t in joined.loc[eligible,"ticker"]))
            reason = "QUALIFIED" if ready else "SOURCE_UNQUALIFIED_IDENTITY_OR_ORIGINAL32"
            if ready:
                snapshot = "CONSENSUS_" + str(day.date())
                need(joined.quarter.nunique() == joined.source_snapshot_id.nunique() == 1,
                     "ONE_AUTHORITATIVE_POOL_PER_DAY")
                schedules.append(dict(snapshot_id=snapshot, universe_id=TASK,
                    quarter=joined.quarter.iloc[0], effective_date=str(day.date()),
                    snapshot_effective_date=str(day.date()), universe_member_count=100,
                    institution_count=institution_count,mapped_count=100))
                joined["snapshot_id"] = snapshot; members.append(joined)
                ledger.append(dict(target_date=day,snapshot_id=snapshot))
                max_keys.update((day,str(t)) for t in joined.loc[~task_excluded,"ticker"])
        if reason != "QUALIFIED": ledger.append(dict(target_date=day,snapshot_id=None))
        detail = dict(nominal_count=len(rows),eligible_count=0,warmup_count=0,task_excluded_count=0,unexplained_count=len(rows))
        if len(rows):
            detail.update(eligible_count=int(eligible.sum()),warmup_count=int(excluded.sum()),
                          task_excluded_count=int(task_excluded.sum()),
                          unexplained_count=int((~(eligible | excluded | task_excluded)).sum()))
        qualifications.append(dict(signal_date=day,status=reason,**detail))
    need(bool(schedules), "NO_COMPLETE_LEGAL_HISTORICAL_POOL")
    ranked, coverage = ranking.ranked_predictions(f, pd.DataFrame(schedules), pd.concat(members),
        pd.DataFrame(ledger), raw_models, list(FEATURES))
    identity = (identities if context_identity is None else context_identity)[["signal_date","ticker","security_id"]].drop_duplicates().copy()
    identity = identity.loc[identity.ticker.notna()]
    identity["is_max_group"] = [(d,str(t)) in max_keys for d,t in zip(identity.signal_date,identity.ticker)]
    flags = flag_owner.assemble_flags(f, ranked, identity)
    # The shared assembler's legacy tag does not certify this task's new rows.
    if context_identity is not None and {"feature_source", "feature_available"} <= set(context_identity):
        rows = context_identity.loc[context_identity.feature_available.eq(True)
                                    & context_identity.feature_source.isin(KNOWN_TASK_RAW_FEATURE_TAGS),
                                    ["signal_date", "ticker", "feature_source"]]
        new_tags = {(d,t):tag for d,t,tag in rows.itertuples(index=False, name=None)}
        restored = pd.Series([new_tags.get((d,t)) for d,t in
                             flags[["signal_date","ticker"]].itertuples(index=False,name=None)], index=flags.index)
        tagged = flags.feature_available.eq(True) & restored.notna()
        flags.loc[tagged, "feature_source"] = restored.loc[tagged]
    # Metadata-only delta: do not mislabel annual historical scoring as 2026 final-model inference.
    flags["raw_a2_oof_split"] = "REBUILT_ANNUAL_OOF_" + flags.signal_date.dt.year.astype(str)
    good_dates = {r["signal_date"] for r in qualifications if r["status"] == "QUALIFIED"}
    unavailable = ~flags.signal_date.isin(good_dates)
    for name in ("is_raw_top20","new_buy_eligible","raw_selector_input_present","decision_information_present_union",
                 "stock_forecast_input_present","input_present"):
        flags.loc[unavailable,name] = False
    need(set(flags.signal_date) == set(calendar), "FULL_2023_PROXY_CONTEXT_CALENDAR_REQUIRED")
    return flags, pd.DataFrame(qualifications), coverage




def pool_source_masks(rows, source_exclusion_keys=()):
    """Separate actual availability, original warmup, and human source exclusion."""
    import pandas as pd
    eligible = rows.feature_available.eq(True)
    warmup = rows.feature_ineligible_qualified.eq(True) & rows.feature_available.eq(False)
    declared = pd.Series([(pd.Timestamp(d),str(c)) in source_exclusion_keys
                          for d,c in rows[["signal_date","cusip"]].itertuples(index=False,name=None)],index=rows.index)
    temporary = declared & rows.feature_available.eq(False) & ~warmup
    return eligible, warmup, temporary


def source_exclusions_from_manifest(manifest, identities):
    """Task-specific human amendment; exact metadata scope, before numerical reads."""
    import pandas as pd
    record = manifest.get("source_exclusion_ref")
    if record is None: return frozenset()
    policy = doc(record)
    allowed = {"M2682V108","418100103","530307305","531229813","531229789"}
    need(policy.get("schema") == "BASE_CONDITIONED_GROSS_USER_SOURCE_EXCLUSION_R1"
         and policy.get("status") == "USER_AUTHORIZED_TEMPORARY_MISSING_SOURCE_EXCLUSION"
         and policy.get("task_id") == TASK and policy.get("scope") == "HISTORY2024"
         and policy.get("cutoff_exclusive") == CUTOFF
         and policy.get("nominal_top_n") == 100 and policy.get("backfill") is False
         and policy.get("dated_identity_ref") == manifest["source_refs"]["dated_identity"]
         and set(policy.get("allowed_cusips",[])) == allowed
         and policy.get("row_count") == 709
         and policy.get("contract_ref",{}).get("sha256") == "2329b8edb6e03ca387c57d83eb28fff41d0cd9ed7cd1aafe978af1eb38eb23ff",
         "EXACT_USER_SOURCE_EXCLUSION_REQUIRED")
    verify(policy["contract_ref"])
    rows = bounded(policy["exclusion_rows_ref"],["signal_date","cusip","ticker","security_id"],"signal_date",first=START)
    need(len(rows) == 709 and not rows.duplicated(["signal_date","cusip"]).any()
         and rows.cusip.isin(allowed).all() and rows[["ticker","security_id"]].notna().all().all(),
         "EXACT_USER_SOURCE_EXCLUSION_KEYS_REQUIRED")
    actual = identities.loc[identities.cusip.isin(allowed) & identities.feature_available.eq(False)
                            & ~identities.feature_ineligible_qualified.eq(True),
                            ["signal_date","cusip","ticker","security_id"]]
    def keys(frame):
        return {(pd.Timestamp(d),str(c),str(t),str(s)) for d,c,t,s in frame.itertuples(index=False,name=None)}
    need(keys(rows) == keys(actual), "USER_SOURCE_EXCLUSION_METADATA_SCOPE_CHANGED")
    return frozenset((pd.Timestamp(d),str(c)) for d,c in rows[["signal_date","cusip"]].itertuples(index=False,name=None))


def metadata_qualified_dates(identity, source_exclusion_keys=()):
    """Reject unknown sources before requesting numerical feature vectors."""
    import pandas as pd
    required = {"signal_date","cusip","ticker","security_id","feature_available","feature_ineligible_qualified"}
    need(required <= set(identity) and not identity.duplicated(["signal_date","cusip"]).any(),
         "FULL_IDENTITY_FEATURE_QUALIFICATION_METADATA_REQUIRED")
    ready = []
    for day, rows in identity.groupby("signal_date",sort=True):
        eligible, excluded, task_excluded = pool_source_masks(rows, source_exclusion_keys)
        if (len(rows) == 100 and rows.ticker.notna().all() and rows.security_id.notna().all()
                and not rows.ticker.duplicated().any() and (eligible | excluded | task_excluded).all() and eligible.sum() >= 20):
            ready.append(pd.Timestamp(day))
    return tuple(ready)


def read_pool(sources):
    """Date-qualified schedule precedes member snapshot projection; retain all100."""
    import pandas as pd
    import pyarrow.dataset as ds
    cols = ["snapshot_id","source_snapshot_id","quarter","effective_date","source_effective_at",
            "universe_member_count","institution_count"]
    schedule = bounded(sources["pool_schedule"],cols,"effective_date",first=START)
    need(schedule.snapshot_id.is_unique and schedule.universe_member_count.eq(100).all(),
         "EXACT_PUBLISHED_POOL_SCHEDULE")
    source = ds.dataset(verify(sources["pool_members"]),format="parquet")
    rule = ds.field("snapshot_id").isin(schedule.snapshot_id.tolist())
    keys = source.scanner(columns=["snapshot_id","cusip"],filter=rule,use_threads=False).to_table().to_pandas()
    need(len(keys) == 100*len(schedule) and not keys.duplicated().any(),"FULL_POOL_KEYS_BEFORE_COVERAGE")
    members = source.scanner(columns=["snapshot_id","cusip","consensus_rank"],filter=rule,use_threads=False).to_table().to_pandas()
    pool = members.merge(schedule,on="snapshot_id",how="left",validate="many_to_one")
    pool["signal_date"] = pd.to_datetime(pool.pop("effective_date"))
    return pool


def action_predictions(flags, calendar, model_bundle):
    import gc
    import joblib
    import numpy as np
    import pandas as pd
    from scripts.research.a2.inference.consensus_paper import original_frames, predict_r10, r10_scaled_input
    from scripts.research.a2.inference.frozen_a94_actions import role_features
    from scripts.research.a2.training import stateful_mechanism as mechanism, stateful_final_action_packets as packets
    output = {b:{} for b in BASES}
    model_cache = {}  # Frozen predictor/scaler pairs live only in this invocation.
    for day in calendar[calendar >= pd.Timestamp(START)]:
        today = flags.loc[flags.signal_date.eq(day)]
        if not today.is_raw_top20.any(): continue
        frames = original_frames(flags.loc[flags.signal_date.le(day)], calendar[calendar <= day], day)
        for base, family in zip(BASES, ("elasticnet","ridge")):
            decoded = []
            for group in ("ENTRY","INCUMBENT"):
                row = model_bundle["nodes"][group]
                key = (base, group)
                if key not in model_cache:
                    model_cache[key] = (joblib.load(verify(row[family + "_model_ref"])),
                                        joblib.load(verify(row[family + "_scaler_ref"])))
                model, scaler = model_cache[key]
                frame = frames[group]
                x, names = mechanism.encode(frame, role_features("R10:" + group))
                need(x.shape[1] == scaler.n_features_in_ and len(names) == x.shape[1],
                     "ORIGINAL_ROLE_ENCODER_AND_SCALER_WIDTH")
                if len(frame):
                    predictions = predict_r10(model, r10_scaled_input(scaler, x))
                    for i, record in enumerate(frame.to_dict("records")):
                        native = {k:float(v[i]) for k,v in predictions.items()
                                  if isinstance(v,np.ndarray) and v.shape == (len(frame),)}
                        decoded.append(packets.decode_r10_row({**record,**native},len(decoded),group=group))
                del model,scaler,x; gc.collect()
            output[base][day] = decoded
    return output


def admitted_feature_sources(manifest, keys):
    """A root task receipt extends only this prepare's source-tag set."""
    from scripts.research.a2.training import stateful_inputs as inputs
    allowed = set(inputs.ALLOWED_SOURCES)
    observed = set(keys.loc[keys.feature_available.eq(True), "feature_source"].dropna())
    observed_new = observed.intersection(KNOWN_TASK_RAW_FEATURE_TAGS)
    receipt_ref = manifest.get("feature_source_admission_ref")
    if receipt_ref is None:
        need(not observed_new, "ROOT_TASK_FEATURE_SOURCE_ADMISSION_REQUIRED")
        return allowed
    receipt = doc(receipt_ref)
    sources = manifest["source_refs"]
    need(receipt.get("status") == "APPROVED_TASK_BOUNDED_ORIGINAL32_SOURCES"
         and receipt.get("task_id") == TASK and receipt.get("cutoff_exclusive") == CUTOFF
         and receipt.get("feature_columns") == list(inputs.FEATURES)
         and receipt.get("source_refs") == {k:sources[k] for k in ("features", "dated_identity")},
         "ROOT_TASK_FEATURE_SOURCE_ADMISSION_CHANGED")
    tags = receipt.get("approved_feature_sources")
    need(isinstance(tags, list) and bool(tags) and len(tags) == len(set(tags))
         and set(tags) <= set(KNOWN_TASK_RAW_FEATURE_TAGS), "EXACT_TASK_FEATURE_SOURCE_TAG_REQUIRED")
    need(observed_new <= set(tags), "ROOT_TASK_FEATURE_SOURCE_TAGS_UNAPPROVED")
    proofs = receipt.get("proof_refs")
    need(isinstance(proofs, dict) and bool(proofs), "ROOT_TASK_FEATURE_SOURCE_PROOF_REQUIRED")
    for proof_ref in proofs.values(): verify(proof_ref)
    allowed.update(tags)
    return allowed


def prepare(manifest, run, finance):
    require_stage(manifest, "prepare")
    import joblib
    import numpy as np
    import pandas as pd
    import pyarrow.dataset as ds
    from scripts.research.a2.training import base_conditioned_gross_run as runner, stateful_inputs as inputs
    from scripts.storage.storage_r2a import write_json_atomic
    sources = manifest["source_refs"]
    out = run / "derived" / "gross_history"
    receipt_path = out / "PREPARED_HISTORY.json"
    if receipt_path.exists():
        old = doc(ref(receipt_path))
        need(old["manifest_ref"] == manifest["_manifest_ref"], "HISTORY_PREPARE_RESUME_IDENTITY")
        verify(old["prepared_ref"]); verify(old["typed_event_ref"])
        return old
    runner.resource_gate(manifest["resource_owner_ref"])
    need(not out.exists(), "INCOMPLETE_PREPARATION_PRESERVED")
    calendar = pd.DatetimeIndex(bounded(sources["calendar"],["trade_date"],"trade_date").trade_date)
    need(calendar[0] == pd.Timestamp(FIRST) and calendar.is_unique and calendar.is_monotonic_increasing,
         "ORIGINAL_COMPLETE_CALENDAR")
    # Keys/qualification projection precedes financial vectors.
    key_columns = ["signal_date","ticker","security_id","feature_available","feature_source"]
    keys = bounded(sources["features"],key_columns,"signal_date")
    allowed_sources = admitted_feature_sources(manifest, keys)
    identities = bounded(sources["dated_identity"],manifest["dated_identity_columns"],"signal_date",first=START)
    need({"signal_date","cusip","ticker","security_id"} <= set(identities),"DATED_POOL_IDENTITY_REQUIRED")
    pool = read_pool(sources)
    source_exclusion_keys = source_exclusions_from_manifest(manifest,identities)
    omitted = identities.loc[[(pd.Timestamp(d),str(c)) in source_exclusion_keys
                              for d,c in identities[["signal_date","cusip"]].itertuples(index=False,name=None)],
                              ["signal_date","ticker"]]
    omitted_tickers = set(omitted.itertuples(index=False,name=None))
    available_keys = set(keys.loc[keys.feature_available.eq(True),["signal_date","ticker"]].itertuples(index=False,name=None))
    need(not available_keys.intersection(omitted_tickers), "EXCLUDED_SOURCE_CANNOT_BE_NUMERICALLY_AVAILABLE")
    need(bool(metadata_qualified_dates(identities,source_exclusion_keys)), "SOURCE_METADATA_NO_ELIGIBLE_HISTORY_SIGNAL")
    eligible = (ds.field("feature_available") == True) & ds.field("feature_source").isin(sorted(allowed_sources))
    features = bounded(sources["features"],["signal_date","ticker",*inputs.FEATURES],"signal_date",extra=eligible)
    raw = {"feature_columns":list(inputs.FEATURES),"artifacts":{}}
    runner.verify_raw_models(manifest["raw_model_manifest_refs"], sources["raw_equivalence"])
    for year, item in manifest["raw_model_manifest_refs"].items():
        raw["artifacts"][year] = doc(item)["artifact"]
    flags, qualification, coverage = rank_history(features,identities,pool,calendar,raw,manifest["pool_institution_count"],context_identity=keys,source_exclusion_keys=source_exclusion_keys)
    # Rank outputs own the required data; release wide input/metadata frames before actions.
    del features, identities, pool, omitted, available_keys, omitted_tickers
    import gc
    gc.collect()
    # Quotes are a separate execution/label coordinate, never predictor features.
    bounded(sources["raw_quotes"],["trade_date","ticker"],"trade_date",first=START)
    quotes = bounded(sources["raw_quotes"],["trade_date","ticker","open","close"],"trade_date",first=START)
    actions = action_predictions(flags,calendar,doc(sources["model_bundle"]))
    source_receipt = doc(manifest["source_preparation_ref"])
    need(source_receipt["status"] == "BOUNDED_TYPED_SOURCES_READY"
         and source_receipt["source_refs"] == {k:sources[k] for k in ("account_source", "bounded_event_binding")},
         "SEPARATE_TYPED_SOURCE_PREPARATION_REQUIRED")
    event_receipt = doc(source_receipt["typed_event_ref"], limit=3_000_000)
    event_binding = doc(sources["bounded_event_binding"], limit=2_000_000)
    out.mkdir(parents=True)
    event_path = out / "TYPED_EVENT_RETENTION.json"
    write_json_atomic(event_path,event_receipt)
    prepared_path = out / "prepared_inputs.joblib"
    with prepared_path.open("xb") as f:
        joblib.dump(dict(calendar=calendar,flags=flags,qualifications=qualification,quotes=quotes,
                         action_packets=actions,event_binding=event_binding,identities=keys),f,compress=3)
    receipt = dict(status="PREPARED_BOUNDED_HISTORY_PENDING_ACCOUNT_RELEASE",manifest_ref=manifest["_manifest_ref"],
        prepared_ref=ref(prepared_path),typed_event_ref=ref(event_path),
        first_signal=START,last_signal=str(calendar[-1].date()),
        cutoff_exclusive=CUTOFF,warmup_pool_qualified=False,
        source_exclusion_ref=manifest.get("source_exclusion_ref"),
        nominal_top_n=100,source_excluded_rows=int(qualification.task_excluded_count.sum()),
        effective_pool_count_min=int(qualification.loc[qualification.status.eq("QUALIFIED"),"eligible_count"].min()),
        effective_pool_count_max=int(qualification.loc[qualification.status.eq("QUALIFIED"),"eligible_count"].max()),
        qualified_dates=int(qualification.status.eq("QUALIFIED").sum()),
        source_unqualified_dates=int(qualification.status.ne("QUALIFIED").sum()),
        real_fits=0,account_paths=0,original32_feature_order=list(inputs.FEATURES))
    write_json_atomic(receipt_path,receipt)
    return receipt


def require_stage(manifest, stage):
    need(manifest.get("schema") == "BASE_CONDITIONED_GROSS_HISTORY_INPUT_R1"
         and manifest.get("task_id") == TASK and manifest.get("driver_ref") == ref(__file__)
         and manifest.get("cutoff_exclusive") == CUTOFF
         and manifest.get("permits", {}).get(stage) is True,
         "ROOT_HISTORY_PHASE_RELEASE_REQUIRED")
    need(manifest.get("status") == "ROOT_SEALED_BOUNDED_HISTORY", "ROOT_HISTORY_SEAL_REQUIRED")


def source_prepare(manifest, run):
    require_stage(manifest, "sources")
    from scripts.research.a2.training import base_conditioned_gross_run as runner
    from scripts.storage.storage_r2a import write_json_atomic
    out = run / "derived" / "gross_history_sources"
    saved = out / "SOURCE_PREPARATION.json"
    identities = {k:manifest["source_refs"][k] for k in ("account_source", "bounded_event_binding")}
    if saved.exists():
        receipt = doc(ref(saved))
        need(receipt["driver_ref"] == ref(__file__) and receipt["source_refs"] == identities,
             "EXISTING_SOURCE_PREPARATION_IDENTITY")
        verify(receipt["typed_event_ref"])
        return receipt
    runner.resource_gate(manifest["resource_owner_ref"])
    need(not out.exists(), "INCOMPLETE_SOURCE_PREPARATION_PRESERVED")
    _, _, _, evidence, _ = typed_events(manifest["source_refs"])
    out.mkdir(parents=True)
    path = out / "TYPED_EVENT_RETENTION.json"
    write_json_atomic(path, evidence)
    receipt = dict(status="BOUNDED_TYPED_SOURCES_READY", driver_ref=ref(__file__),
                   source_refs=identities, typed_event_ref=ref(path), cutoff_exclusive=CUTOFF,
                   actual_fits=0, account_paths=0, future_event_payloads_decoded=0)
    write_json_atomic(saved, receipt)
    return receipt


def feature_provider(flags, tickers):
    """Signal-only callback for the existing recorder and conditional overlay."""
    import numpy as np
    import pandas as pd
    from scripts.research.a2.training.stateful_inputs import FEATURES
    need(not flags.duplicated(["signal_date", "ticker"]).any(), "SIGNAL_FEATURE_KEYS_UNIQUE")
    frames = {pd.Timestamp(d): rows.set_index("ticker") for d,rows in flags.groupby("signal_date",sort=False)}
    names = tuple(map(str, tickers))
    def provide(di, context, row):
        need(tuple(map(str,context.tickers)) == names, "SIGNAL_FEATURE_AXIS_CHANGED")
        day = pd.Timestamp(context.signal_date)
        need(day in frames, "SIGNAL_FEATURE_DAY_MISSING")
        current = frames[day].reindex(names)
        keys = tuple((t, str(sid) if pd.notna(sid) else "UNAVAILABLE")
                     for t,sid in zip(names,current.security_id))
        return keys, current[list(FEATURES)].to_numpy(float), current.raw_a2_prediction.to_numpy(float)
    return provide


def original_h5_extension(packet, extension, owner_ref):
    """Execute the original owner's H5 exact-reuse block without copying rules."""
    import numpy as np
    import pandas as pd
    tree = ast.parse(verify(owner_ref).read_text(encoding="utf-8-sig"))
    funcs = [node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name == "build_real_frames"]
    need(len(funcs) == 1, "ORIGINAL_LABEL_FUNCTION_REQUIRED")
    blocks = [n for n in ast.walk(funcs[0]) if isinstance(n,ast.If)
              and ast.dump(n.test,include_attributes=False) == ast.dump(ast.parse("h == 5",mode="eval").body,include_attributes=False)]
    need(len(blocks) == 1, "ORIGINAL_EXACT_H5_REUSE_BLOCK_REQUIRED")
    scope = dict(np=np,pd=pd,packet=packet,extension=extension,h=5)
    exec(compile(ast.fix_missing_locations(ast.Module(body=blocks,type_ignores=[])),owner_ref["path"],"exec"),scope)
    return scope["packet"]


def label_callbacks(records, prepared, sources):
    """Fixed targets first; original endpoint plan then mature-only label reads."""
    import numpy as np
    import pandas as pd
    import pyarrow.dataset as ds
    from scripts.research.a2.training import stateful_mechanism_inputs as owner
    keys = [{"signal_date":rec["signal_date"],"ticker":ticker,"security_id":sid}
            for rec in records if rec["status"] == "TARGET_RECORDED" for ticker,sid in rec["keys"]]
    if not keys:
        return lambda record: None, lambda record,**kw: None
    keys = pd.DataFrame(keys).drop_duplicates().sort_values(["signal_date","ticker"]).reset_index(drop=True)
    event_owner = module(sources["label_event_owner"],"_gross_history_original_label_events")
    plan = owner.native_endpoint_plan(keys,prepared["calendar"],5,prepared["identities"],
        prepared["quotes"][["trade_date","ticker"]],prepared["event_binding"]["event_records"],
        event_owner.apply_event_windows,"BASE_CONDITIONED_GROSS_ORIGINAL_NATIVE_H5")
    index = plan.set_index(["signal_date","ticker","security_id"])
    need(index.index.is_unique,"FIXED_LABEL_KEYS_UNIQUE")
    cache = {}
    def selected(rec):
        return index.reindex([(pd.Timestamp(rec["signal_date"]),t,s) for t,s in rec["keys"]]).reset_index()
    def clock(rec):
        return selected(rec).label_mature_date.tolist()
    def values(rec, *, cutoff):
        need(pd.Timestamp(cutoff) == pd.Timestamp(CUTOFF), "EXACT_LABEL_READ_CUTOFF")
        day = pd.Timestamp(rec["signal_date"])
        packet = selected(rec)
        need(packet.label_mature_date.notna().all() and packet.label_mature_date.lt(CUTOFF).all(),
             "NO_UNMATURED_LABEL_NUMERIC_READ")
        key = (day,tuple(rec["keys"]))
        if key not in cache:
            # This gate is applied inside the scanner, before economic decode.
            rule = ((ds.field("signal_date") == day.to_pydatetime())
                    & (ds.field("label_available") == True)
                    & ds.field("ticker").isin([t for t,s in rec["keys"]]))
            parent_cols = ["signal_date","ticker","security_id","label_available","label_mature_date","label_coordinate"]
            bounded(sources["parent_labels"],parent_cols,"signal_date",first=START,
                    second_clock="label_mature_date",extra=rule)
            parent = bounded(sources["parent_labels"],[*parent_cols,"y_open5"],"signal_date",first=START,
                             second_clock="label_mature_date",extra=rule)
            extension_cols = ["signal_date","ticker","label_available","label_mature_date","label_unsupported_common_event"]
            bounded(sources["five_day_extension"],extension_cols,"signal_date",first=START,
                    second_clock="label_mature_date",extra=rule)
            extension = bounded(sources["five_day_extension"],[*extension_cols,"label_quantity_multiplier","y_open5"],
                                "signal_date",first=START,second_clock="label_mature_date",extra=rule)
            packet = owner.native_labels(packet,prepared["quotes"],parent5=parent)
            packet = original_h5_extension(packet,extension,sources["label_owner"])
            cache[key] = packet
        packet = cache[key]
        need(pd.to_datetime(packet.label_mature_date).equals(pd.to_datetime(selected(rec).label_mature_date)),
             "ORIGINAL_LABEL_CLOCK_MUST_MATCH_REQUEST")
        if not packet.label_qualified.eq(True).all(): return None
        result = packet.label_value.to_numpy(float)
        return result if np.isfinite(result).all() else None
    return clock, values


def account(manifest, run, finance):
    require_stage(manifest,"account")
    import joblib
    import pandas as pd
    from scripts.research.a2.evaluation import frozen_test_authority as authority
    from scripts.research.a2.inference import stateful_test_inputs
    from scripts.research.a2.evaluation import aggregate_13f_retest
    from scripts.research.a2.training import base_conditioned_gross_run as runner
    from scripts.research.a2.training import stateful_final_action, stateful_final_action_packets as packets
    from scripts.storage.storage_r2a import write_json_atomic
    release_ref = manifest["account_release_ref"]
    admitted = authority.load_descriptive_authority(dict(schema="BASE_CONDITIONED_GROSS_ACCOUNT_AUTHORITY_REF_R1",
        task_id=TASK,release_ref=release_ref,window_id="HISTORY2024"))
    candidates = manifest["candidate_specs"]
    need(tuple(c["candidate_id"] for c in candidates) == BASES,"EXACT_BASE_ACCOUNT_ORDER")
    admitted = authority.validate_descriptive_policy(admitted,candidates)
    preparation = doc(manifest["prepared_history_ref"])
    out = run / "gross_history_account"
    saved = out / "ACCOUNT_RECEIPT.json"
    identity = {k:manifest[k] for k in ("driver_ref","account_release_ref","prepared_history_ref","candidate_specs","account_config")}
    if saved.exists():
        receipt = doc(ref(saved))
        need(receipt["identity"] == identity and receipt["status"] == "ACCOUNT_COMPLETE", "HISTORICAL_ACCOUNT_ALREADY_STARTED")
        verify(receipt["records_ref"])
        return receipt
    runner.resource_gate(manifest["resource_owner_ref"])
    need(not out.exists(), "INCOMPLETE_HISTORICAL_ACCOUNT_PRESERVED_NO_SECOND_RUN")
    prepared = joblib.load(verify(preparation["prepared_ref"]))
    dates = prepared["calendar"][prepared["calendar"] >= pd.Timestamp(START)]
    need(dates[-1] < pd.Timestamp(CUTOFF),"BOUND_HISTORY_ACCOUNT_DATES")
    old = module(manifest["source_refs"]["account_source"],"_gross_history_account_functions")
    window = stateful_test_inputs.project_window(prepared["flags"],prepared["quotes"],dates,admitted,values_function=old.values)
    market = window["market"]
    packet = aggregate_13f_retest.raw_diagnostic_packet(dates,market.tickers)
    overlay = stateful_final_action.FinalActionOverlay(candidates,{"ridge":packet},window["top"],window["qualified"],window["vol"],
        action_packets=prepared["action_packets"],resource_decoder=packets.decode_resource_proposals,
        sid_by_key=window["sid_by_key"],descriptive_evaluation_authority=admitted)
    recorder = runner.SignalTargetRecorder(BASES,overlay,feature_provider(prepared["flags"],market.tickers))
    events = doc(preparation["typed_event_ref"],limit=3_000_000)
    from scripts.v22.corporate_action_transition_r1 import CorporateActionTransition
    actions = tuple(CorporateActionTransition(**row) for row in events["corporate_actions"])
    known = {key:pd.Timestamp(value) for key,value in events["corporate_action_known_at"].items()}
    cfg = old.config_adapter(manifest["account_config"])
    need(cfg["initial_cash"] == 3000 and cfg["initial_holdings"] == [],"FRESH_HISTORY3000")
    out.mkdir()
    write_json_atomic(saved,dict(status="ACCOUNT_STARTED",identity=identity,account_paths=2,actual_fits=0))
    try:
        result = finance.run_continuous_account(market,BASES,recorder,cfg,corporate_actions=actions,
            corporate_action_known_at=known,unsupported_events=events["unsupported_events"],
            execution_friction=candidates[0]["execution_friction"],descriptive_evaluation_authority=admitted)
        qualified = set(prepared["qualifications"].loc[prepared["qualifications"].status.eq("QUALIFIED"),"signal_date"])
        for record in recorder.records:
            if record["signal_date"] not in qualified: record["status"] = "SOURCE_UNQUALIFIED"
        record_path = out / "signal_targets.joblib"
        with record_path.open("xb") as stream: joblib.dump(recorder.records,stream,compress=3)
        ledgers = {}
        for name in ("orders","fills","positions","nav"):
            frame = getattr(result,name,None)
            if frame is not None:
                path = out / (name + ".parquet"); frame.to_parquet(path,index=False); ledgers[name] = ref(path)
        receipt = dict(status="ACCOUNT_COMPLETE",identity=identity,records_ref=ref(record_path),ledger_refs=ledgers,
                       account_paths=2,actual_fits=0,target_capture=runner.history_config()["target_capture"])
        write_json_atomic(saved,receipt)
        return receipt
    except BaseException as exc:
        write_json_atomic(saved,dict(status="ACCOUNT_FAILED_PRESERVED",identity=identity,
                          account_paths=2,actual_fits=0,error=type(exc).__name__+":"+str(exc)))
        raise


def samples(manifest,run):
    require_stage(manifest,"samples")
    import joblib
    from scripts.research.a2.training import base_conditioned_gross_run as runner
    from scripts.storage.storage_r2a import write_json_atomic
    receipt = doc(manifest["account_receipt_ref"])
    need(receipt["status"] == "ACCOUNT_COMPLETE", "COMPLETE_HISTORY_ACCOUNT_REQUIRED")
    source_refs = dict(manifest["sample_source_refs"],historical_application=manifest["account_receipt_ref"])
    saved = run / "gross_samples" / "SAMPLE_RECEIPT.json"
    if saved.exists():
        old = doc(ref(saved))
        need(old["source_refs"] == source_refs and old["status"] == "SAMPLES_READY","SAMPLE_IDENTITY_CHANGED")
        for record in old["samples"].values(): verify(record)
        return dict(status="SAMPLES_READY",sample_receipt_ref=ref(saved))
    runner.resource_gate(manifest["resource_owner_ref"])
    preparation = doc(manifest["prepared_history_ref"])
    prepared = joblib.load(verify(preparation["prepared_ref"]))
    records = joblib.load(verify(receipt["records_ref"]))
    clock, values = label_callbacks(records,prepared,manifest["source_refs"])
    frames, exclusions = runner.build_samples(records,clock,values)
    sample_ref = runner.save_samples(run,frames,exclusions,source_refs)
    draft = runner.manifest_template(run)
    draft.update(sample_receipt_ref=sample_ref,raw_model_manifest_refs=manifest["raw_model_manifest_refs"],
                 resource_owner_ref=manifest["resource_owner_ref"],required_unknown=["root_train_release"])
    draft_path = run / "GROSS_TRAIN_RELEASE_DRAFT.json"
    write_json_atomic(draft_path,draft)
    return dict(status="SAMPLES_READY",sample_receipt_ref=sample_ref,train_release_draft_ref=ref(draft_path))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest",required=True)
    parser.add_argument("--manifest-sha",required=True)
    parser.add_argument("--stage",choices=("metadata","sources","prepare","account","samples"),default="metadata")
    args = parser.parse_args(argv)
    manifest_ref = dict(path=str(Path(args.manifest).resolve()),sha256=args.manifest_sha)
    manifest = doc(manifest_ref)
    need(manifest["task_id"] == TASK and manifest["driver_ref"] == ref(__file__)
         and manifest["cutoff_exclusive"] == CUTOFF,"HISTORY_INPUT_IDENTITY")
    if args.stage == "metadata":
        print(json.dumps(dict(status="METADATA_ONLY",numerical_reads=0,actual_fits=0,account_paths=0)))
        return
    require_stage(manifest,args.stage)
    # Strictly precedes runner/policy/event/fast-account imports.
    from scripts.research.a2.evaluation import base_conditioned_gross_runtime as runtime
    finance = runtime.bootstrap(manifest["runtime_binding_ref"],phase="HISTORY2024")
    from scripts.research.a2.evaluation import base_conditioned_gross_profile as profile
    profile.install_routes(manifest["runtime_binding_ref"],"HISTORY2024")
    from scripts.common.storage_paths import resolve, assert_safe_output_path
    from scripts.research.a2.training.stateful_execution import continuation_lock
    run = Path(manifest["run_root"]).resolve()
    paths = resolve(); assert_safe_output_path(run,kind="backtest",paths=paths)
    need(run.parent.name == TASK and run.is_dir(),"EXISTING_TASK_RUN_REQUIRED")
    manifest["_manifest_ref"] = manifest_ref
    with continuation_lock(run,manifest["driver_ref"]["sha256"],namespace=TASK+":HISTORY"):
        if args.stage == "sources": result = source_prepare(manifest,run)
        elif args.stage == "prepare": result = prepare(manifest,run,finance)
        elif args.stage == "account": result = account(manifest,run,finance)
        else: result = samples(manifest,run)
    print(json.dumps({key:value for key,value in result.items() if key in ("status","sample_receipt_ref","train_release_draft_ref")}))


if __name__ == "__main__":
    main()
