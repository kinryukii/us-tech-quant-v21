"""Current-only R6 mature probes; original target/cohort kernels, no fit or SDK.

The old pre2026 target owner remains unchanged. This adapter admits exact
current source references, uses actual observation clocks, and never certifies
an unknown source as an empty risk set. First version accepts no-event windows
only; current event classification remains with its original owner.
"""
from __future__ import annotations
import csv
import io
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

SCHEMA = "CURRENT_R6_PROBE_SOURCE_V1"
CANDIDATE = "R6_DURATION_TREE"
EVENT_OWNER = {"path": "D:/us-tech-quant-results/A2_STATEFUL_ACTION_AND_CASH_PRE2026_TEST2026_R1/LABEL_REPAIR_R1.py",
    "sha256": "7ab35af794d1cbc5df1de84d72891bd5ff2605cbd44f6a1bfe0eff417fa74b59"}
KEYS = ("signal_date", "ticker", "security_id")
META = (*KEYS, "feature_available", "is_raw_top20", "new_buy_eligible", "raw_top20_set_complete", "raw_a2_rank", "raw_a2_prediction")


def _need(ok, reason):
    if not ok:
        raise ValueError(reason)


def _digest(path):
    with Path(path).open("rb") as h:
        return hashlib.file_digest(h, "sha256").hexdigest()


def _ref(path):
    return {"path": str(Path(path).resolve()), "sha256": _digest(path)}


def _verified(ref):
    p = Path(ref["path"]).resolve()
    _need(p.is_file() and _digest(p) == ref.get("sha256"), "R6_CURRENT_SOURCE_CHANGED")
    return p


def _clock(value):
    t = pd.Timestamp(value)
    _need(not pd.isna(t) and t.tzinfo is not None, "R6_CURRENT_OBSERVATION_CLOCK_REQUIRED")
    return t.tz_convert("UTC")


def _scope(signal_date, decision_as_of):
    day, observed = pd.Timestamp(signal_date), _clock(decision_as_of)
    _need(day.tzinfo is None and day == day.normalize() and pd.Timestamp("2026-01-01") <= day < pd.Timestamp("2027-01-01"), "R6_CURRENT_2026_SIGNAL_REQUIRED")
    _need(observed >= day.tz_localize("America/New_York") + pd.Timedelta(hours=16), "R6_CURRENT_COMPLETED_SIGNAL_REQUIRED")
    return day, observed


def _scan(ref, columns, date_column, first, last):
    p = _verified(ref)
    schema = pq.read_schema(p)
    _need(set(columns).issubset(schema.names), "R6_CURRENT_SOURCE_SCHEMA_REQUIRED")
    field = ds.field(date_column)
    lo, hi = (str(pd.Timestamp(v).date()) if (pa.types.is_string(schema.field(date_column).type) or pa.types.is_large_string(schema.field(date_column).type)) else pd.Timestamp(v).to_pydatetime() for v in (first, last))
    dataset = ds.dataset(p, format="parquet")
    scanner = table = None
    try:
        scanner = dataset.scanner(columns=list(columns), filter=(field >= lo) & (field <= hi),
            use_threads=False, batch_readahead=1, fragment_readahead=1)
        table = scanner.to_table()
        return table.to_pandas(split_blocks=True, use_threads=False)
    finally:
        dataset = scanner = table = None
        from scripts.research.a2.inference.consensus_paper import _release_arrow_cache
        _release_arrow_cache()


def _kernels(day):
    from scripts.research.a2.inference import frozen_a94_state as state
    from scripts.research.a2.training import stateful_decision as decision
    for module in (state.foundation, decision, state.mechanism_inputs, state.mechanism, state.original_inputs):
        _need(_digest(module.__file__) == state._PINS[module.__name__], "R6_CURRENT_ORIGINAL_KERNEL_CHANGED")
    legal = state._clone(decision._legal_label, inputs=state._DateInputs(day))
    sample = state._clone(decision._sample, _legal_label=legal)
    build = state._clone(decision.build_samples, inputs=state._DateInputs(day + pd.Timedelta(days=1)), _sample=sample, _legal_label=legal)
    return state, decision, build


def _calendar(value, day):
    cal = pd.DatetimeIndex(pd.to_datetime(value))
    _need(len(cal) > 1 and cal[0] == pd.Timestamp("2023-01-03") and cal[-1] == day
        and cal.is_unique and cal.is_monotonic_increasing, "R6_CURRENT_ORIGINAL_COHORT_PHASE_REQUIRED")
    return cal


from scripts.research.a2.inference.consensus_paper import _ScopedProxyRows


class _DiscardSampleRows(list):
    def append(self, row):
        pass


class _SampleResultRows(_ScopedProxyRows):
    def __init__(self, prediction, first, last, projection):
        super().__init__(prediction.iloc[:0], first, last)
        self.projection = projection

    def append(self, row):
        if self.projection is not None:
            row = {name: row[name] for name in self.projection}
        # Retain scalar-category witnesses for every column, including labels,
        # to preserve the original full-history DataFrame dtype inference.
        if self.columns is None:
            self.variable = set(row)
        super().append(row)


def _projected_samples(build, prediction, labels, calendar, day, objective):
    """Only change original result storage; every transition and audit still runs."""
    import ast
    import gc
    import inspect
    import textwrap
    from copy import deepcopy
    from scripts.research.a2.training import stateful_decision as decision
    from scripts.research.a2.inference.consensus_paper import _ProxySchemaFallback
    _need(build.__code__ is decision.build_samples.__code__ and objective in ("hold", "duration"),
        "R6_CURRENT_ORIGINAL_BUILD_STORAGE_REQUIRED")
    original = ast.parse(textwrap.dedent(inspect.getsource(decision.build_samples)))
    tree = deepcopy(original)
    seams = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
        and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "samples"]
    _need(len(seams) == 1 and ast.unparse(seams[0].value) == "{o: [] for o in (*OBJECTIVES, 'gross')}",
        "R6_CURRENT_BUILD_STORAGE_SEAM_CHANGED")
    previous = seams[0].value
    seams[0].value = ast.Name(id="_projected_result_storage", ctx=ast.Load())
    restored = deepcopy(tree)
    restore = next(node for node in ast.walk(restored) if isinstance(node, ast.Assign)
        and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "samples")
    restore.value = previous
    _need(ast.dump(restored, include_attributes=False) == ast.dump(original, include_attributes=False),
        "R6_CURRENT_BUILD_ALGORITHM_CHANGED")
    rows = _SampleResultRows(prediction, calendar[0] if objective == "hold" else day, day,
        (*KEYS, "cohort_id", "cohort_age_sessions") if objective == "hold" else None)
    storage = {name: rows if name == objective else _DiscardSampleRows() for name in (*decision.OBJECTIVES, "gross")}
    namespace = dict(build.__globals__)
    namespace["_projected_result_storage"] = storage
    exec(compile(ast.fix_missing_locations(tree), inspect.getsourcefile(decision.build_samples), "exec"), namespace)
    try:
        result = namespace[decision.build_samples.__name__](prediction, labels, calendar)
    except _ProxySchemaFallback:
        result = None
    finally:
        namespace.pop(decision.build_samples.__name__, None)
        namespace.pop("_projected_result_storage", None)
    if result is None:
        del namespace, storage, rows
        gc.collect()
        return build(prediction, labels, calendar)
    return result


def _validate_structural_keys(pred, calendar):
    _need(set(pred.signal_date) == set(calendar) and not pred.duplicated(["signal_date", "ticker"]).any(), "R6_CURRENT_COMPLETE_PREDICTION_KEYS_REQUIRED")
    for key in ("feature_available", "is_raw_top20", "new_buy_eligible", "raw_top20_set_complete"):
        _need(pred[key].notna().all() and pred[key].isin((True, False)).all(), "R6_CURRENT_FLAGS_UNBOUND")


def _structural(prediction, calendar, day):
    state, decision, build = _kernels(day)
    pred = prediction[list(META)].copy()
    pred["signal_date"] = pd.to_datetime(pred.signal_date)
    _validate_structural_keys(pred, calendar)
    # Features do not choose cohort membership. Original structural keys use the
    # same zero-valued placeholders; genuine feature availability stays intact.
    pred = pred.assign(**{f: 0. for f in state.original_inputs.FEATURES})
    frames, _ = _projected_samples(build, pred, pd.DataFrame(columns=decision.LABEL_COLS), calendar, day, "hold")
    hold = frames["hold"]
    if hold.empty:
        return pd.DataFrame(columns=[*KEYS, "cohort_id", "cohort_age_sessions"])
    return hold[[*KEYS, "cohort_id", "cohort_age_sessions"]].copy()


def needed_probe_keys(prediction, calendar, signal_date):
    """Exact predecessor dependency, not an arbitrary last-N label window.

    At current ages7/14 only the same cohort's age0/7 positive mature probes
    can keep the original risk set alive. Age0 requires no previous outcome.
    Other cohorts cannot influence this day's original duration frame.
    """
    day = pd.Timestamp(signal_date); cal = _calendar(calendar, day)
    hold = _structural(prediction, cal, day)
    return _probe_keys_from_hold(hold, cal, day)


def _probe_keys_from_hold(hold, cal, day):
    """Reuse the original no-label cohort output; no second history replay."""
    if hold.empty:
        hold = pd.DataFrame(columns=[*KEYS, "cohort_id", "cohort_age_sessions"])
    current = hold.loc[hold.signal_date.eq(day) & hold.cohort_age_sessions.isin((7, 14))]
    parts = []
    for row in current.itertuples():
        parts.append(hold.loc[hold.cohort_id.eq(row.cohort_id) & hold.cohort_age_sessions.isin(range(0, int(row.cohort_age_sessions), 7))])
    keys = pd.concat(parts, ignore_index=True) if parts else hold.iloc[:0]
    keys = keys.drop_duplicates(list(KEYS))[list(KEYS)].sort_values(list(KEYS)).reset_index(drop=True)
    index = {d:i for i,d in enumerate(cal)}
    keys["execution_date"] = keys.signal_date.map(lambda d: cal[index[d]+1])
    keys["label_mature_date"] = keys.signal_date.map(lambda d: cal[index[d]+6])
    _need(keys.label_mature_date.lt(day).all(), "R6_CURRENT_UNMATURED_DEPENDENCY")
    return keys


def _selected_leaf_opens(path, wanted):
    """Decode open only after a streamed raw row matches an admitted endpoint."""
    result = {}
    if Path(path).suffix.lower() == ".csv":
        with Path(path).open(encoding="utf-8-sig", newline="") as h:
            for row in csv.DictReader(h):
                code = row.get("code") or row.get("provider_code") or row.get("moomoo_symbol")
                stamp = row.get("trade_date") or row.get("date") or row.get("time_key")
                key = (code, str(stamp)[:10])
                if key not in wanted:
                    continue
                _need(key not in result, "R6_CURRENT_RAW_ENDPOINT_DUPLICATE")
                stamp = row.get("fetched_at_utc") or row.get("fetch_timestamp") or row.get("observed_at")
                _need(stamp is not None,"R6_CURRENT_RAW_LEAF_OBSERVATION_UNBOUND")
                result[key] = (float(row["open"]),_clock(stamp))
    elif Path(path).suffix.lower() == ".json":
        # Massive grouped daily leaf: metadata T is inspected before any o value.
        from scripts.common.json_projection import _parser_type
        parser = _parser_type()
        with Path(path).open("rb") as h:
            r = parser(h); r.descend(("results",)); r.expect(b"["); r.white()
            while r.peek() != b"]":
                start = r.tell(); meta = r.metadata_fields({"T"}); stop = r.tell()
                matches = [key for key in wanted if key[0] == meta.get("T")]
                if matches:
                    with Path(path).open("rb") as selected:
                        selected.seek(start)
                        _need(stop-start<=65536,"R6_CURRENT_RAW_RECORD_BOUND")
                        values = parser(io.BytesIO(selected.read(stop-start))).metadata_fields({"T", "o"})
                    _need(len(matches) == 1 and matches[0] not in result, "R6_CURRENT_RAW_ENDPOINT_DUPLICATE")
                    result[matches[0]] = (float(values["o"]),None)
                r.white()
                if r.peek() == b",":r.take();r.white()
                else:break
    else:
        raise ValueError("R6_CURRENT_RAW_LEAF_FORMAT_UNSUPPORTED")
    _need(set(result) == set(wanted), "R6_CURRENT_RAW_ENDPOINT_SOURCE_INCOMPLETE")
    return result


def _raw_endpoints_one(store, ticker, dates, observed, dataset):
    record = store.metadata(dataset, ticker, "raw")
    expected = "MOOMOO_OPEND" if dataset=="prices_daily" else "MASSIVE_GROUPED"
    _need(record.get("dataset")==dataset and record.get("ticker")==ticker and record.get("source")==expected
        and record.get("adjustment")=="raw" and record.get("format")=="parquet", "R6_CURRENT_RAW_CATALOG_REQUIRED:"+ticker)
    if expected=="MASSIVE_GROUPED":
        lineage=record.get("lineage") or json.loads(record.get("lineage_json") or "{}")
        mapping=lineage.get("provider_mapping",{})
        _need(lineage.get("provider")==expected and lineage.get("price_basis")=="RAW" and lineage.get("currency")=="USD"
            and lineage.get("exchange_timezone")=="America/New_York" and lineage.get("provider_symbol")==ticker
            and mapping.get("provider_symbol")==ticker,"R6_CURRENT_MASSIVE_SOURCE_IDENTITY_REQUIRED")
    p = _verified({"path":record["path"],"sha256":record["source_sha256"]})
    refs = store.resolve_price_inputs(record, verify_raw=False)
    by_sha = {v["sha256"]:v for v in refs}
    schema = pq.read_schema(p); names = schema.names
    cols = ["date","ticker","source","adjustment","provider_code","source_id","observed_at"]
    if "currency" in names:cols.append("currency")
    _need(set(cols+['open']).issubset(names), "R6_CURRENT_RAW_METADATA_SCHEMA_REQUIRED:" + ticker)
    date_type = schema.field("date").type
    allowed = sorted(dates)
    filter_dates = allowed if (pa.types.is_string(date_type) or pa.types.is_large_string(date_type)) else [pd.Timestamp(d).to_pydatetime() for d in allowed]
    predicate = ds.field("date").isin(filter_dates) & (ds.field("ticker") == ticker)
    metadata = ds.dataset(p, format="parquet").to_table(columns=cols,filter=predicate).to_pandas()
    metadata["date"] = metadata.date.astype(str).str[:10]
    if metadata.empty:
        return {},{},[]
    _need(not metadata.date.duplicated().any(), "R6_CURRENT_RAW_ENDPOINT_COVERAGE:" + ticker)
    if "currency" in metadata:
        _need(metadata.currency.eq("USD").all(),"R6_CURRENT_RAW_CURRENCY_REQUIRED")
    elif expected=="MASSIVE_GROUPED":
        raise ValueError("R6_CURRENT_RAW_CURRENCY_REQUIRED")
    code = "US."+ticker if record["source"] == "MOOMOO_OPEND" else ticker
    _need(metadata.ticker.eq(ticker).all() and metadata.provider_code.eq(code).all() and metadata.source.eq(record["source"]).all()
        and metadata.adjustment.eq("raw").all() and metadata.source_id.isin(by_sha).all(), "R6_CURRENT_RAW_IDENTITY_UNBOUND:"+ticker)
    clocks = {row.date:_clock(row.observed_at) for row in metadata.itertuples()}
    _need(all(pd.Timestamp(d).tz_localize("America/New_York")+pd.Timedelta(hours=16)<=v<=observed for d,v in clocks.items()), "R6_CURRENT_FUTURE_RAW_OBSERVATION:"+ticker)
    raw_groups = {}; checkpoint_refs = []
    for row in metadata.itertuples():
        ref = by_sha[row.source_id]; _verified(ref)
        raw_groups.setdefault((ref["path"],ref["sha256"]),set()).add((code,row.date))
        if record["source"] == "MASSIVE_GROUPED":
            checkpoint=Path(ref["path"]).parent/"checkpoint.json"
            _need(checkpoint.is_file() and checkpoint.stat().st_size<=65536,"R6_CURRENT_MASSIVE_CHECKPOINT_REQUIRED")
            check=json.loads(checkpoint.read_text(encoding="utf-8")); checkpoint_refs.append(_ref(checkpoint))
            from scripts.storage.refresh_massive_market import ENDPOINT
            _need(check.get("contract",{}).get("url")==ENDPOINT+row.date,"R6_CURRENT_MASSIVE_ENDPOINT_REQUIRED")
            _need(check.get("status")=="SUCCESS" and check.get("raw",{}).get("sha256")==ref["sha256"]
                and Path(check.get("raw",{}).get("path","")).resolve()==Path(ref["path"]).resolve()
                and check.get("contract",{}).get("date")==row.date
                and check.get("contract",{}).get("params")=={"adjusted":"false","include_otc":"false"}
                and _clock(check.get("observed_at"))==clocks[row.date],"R6_CURRENT_MASSIVE_CHECKPOINT_CHANGED")
            _need(_clock(ref.get("observed_at")) == clocks[row.date] and ref.get("date")==row.date, "R6_CURRENT_MASSIVE_CLOCK_UNBOUND")
    # Only this exact mature endpoint set reaches numerical decoding.
    values = ds.dataset(p,format="parquet").to_table(columns=["date","open"],filter=predicate).to_pandas()
    values["date"] = values.date.astype(str).str[:10]
    opens = dict(zip(values.date,values.open))
    for (leaf,sha),wanted in raw_groups.items():
        original = _selected_leaf_opens(leaf,wanted)
        _need(all(np.isfinite(opens[d]) and opens[d]>0 and float(opens[d])==original[(c,d)][0] and (original[(c,d)][1] is None or original[(c,d)][1]==clocks[d]) for c,d in wanted), "R6_CURRENT_RAW_SOURCE_VALUE_MISMATCH")
    return opens,clocks,[{"path":str(p),"sha256":record["source_sha256"]},*[{"path":p,"sha256":s} for p,s in raw_groups],*checkpoint_refs]



def _raw_endpoints(store, ticker, dates, observed):
    opens,clocks,refs={},{},[]
    for dataset in ("prices_daily","prices_daily_massive"):
        missing=set(dates)-set(opens)
        if not missing:break
        try:
            values,times,physical=_raw_endpoints_one(store,ticker,missing,observed,dataset)
        except (KeyError,FileNotFoundError):
            continue
        opens.update(values);clocks.update(times);refs.extend(physical)
    _need(set(opens)==set(dates),"R6_CURRENT_RAW_ENDPOINT_COVERAGE:"+ticker)
    return opens,clocks,refs


def _save_immutable(path, value):
    body = json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n"
    if path.exists():_need(path.read_text(encoding="utf-8")==body,"R6_CURRENT_PRESERVE_EXISTING_PROOF")
    else:path.write_text(body,encoding="utf-8")
    return _ref(path)



def _factor_dates(row, ticker, cache):
    ref={k:row[k] for k in ('path','sha256')}
    key=(ref['path'],ref['sha256'],ticker)
    if key not in cache:
        path=_verified(ref);schema=pq.read_schema(path)
        _need({'code','ex_div_date'}.issubset(schema.names),'R6_CURRENT_REHAB_SCHEMA:'+ticker)
        events=pq.read_table(path,columns=['code','ex_div_date']).to_pandas()
        _need(len(events)==row.get('row_count') and (events.empty or events.code.eq('US.'+ticker).all()),'R6_CURRENT_REHAB_IDENTITY:'+ticker)
        dates=pd.to_datetime(events.ex_div_date)
        _need(dates.notna().all(),'R6_CURRENT_REHAB_EVENT_CLOCK_UNBOUND:'+ticker)
        cache[key]=(dates,ref)
    return cache[key]


def _historical_rehab(paths, probe, deadline, observed, cache):
    """Use actual earlier accepted captures; no synthetic historical timestamps."""
    from scripts.research.a2.inference.consensus_current_inputs import accepted_daily_report_metadata
    mature=str(probe.label_mature_date.date())
    if mature not in cache:
        cache[mature]=accepted_daily_report_metadata(paths,mature,deadline=deadline)
    eligible=[]
    lower=probe.label_mature_date.tz_localize('America/New_York')+pd.Timedelta(hours=16)
    for capture in cache[mature]:
        if _clock(capture['generated_at'])>observed:continue
        receipt_ref=capture['rehab_ref'];receipt_path=_verified(receipt_ref)
        doc=json.loads(receipt_path.read_text(encoding='utf-8'))
        _need(doc.get('source')=='MOOMOO_OPEND_GET_REHAB' and doc.get('target_date')==mature
            and doc.get('status') in ('READY','PARTIAL'),'R6_CURRENT_HISTORICAL_REHAB_IDENTITY')
        matches=[r for r in doc.get('results',[]) if r.get('code')=='US.'+probe.ticker and r.get('status')=='PASS']
        _need(len(matches)<=1,'R6_CURRENT_DUPLICATE_REHAB_CODE')
        if not matches:continue
        row=matches[0];clock=_clock(row.get('fetched_at'))
        if not lower<=clock<=min(deadline,observed):continue
        mapping=_verified(capture['mapping_ref'])
        schema=pq.read_schema(mapping)
        _need({'ticker','security_id'}.issubset(schema.names),'R6_CURRENT_HISTORICAL_MAPPING_SCHEMA')
        identity=pq.read_table(mapping,columns=['ticker','security_id'],filters=[('ticker','==',probe.ticker)]).to_pandas()
        if len(identity)!=1 or str(identity.security_id.iloc[0])!=str(probe.security_id):continue
        eligible.append((clock,capture,row))
    if not eligible:return None
    clock,capture,row=min(eligible,key=lambda item:(item[0],item[1]['source_ref']['sha256']))
    refs={'capture':capture['capture_ref'],'accepted_source':capture['source_ref'],'rehab_receipt':capture['rehab_ref'],'mapping':capture['mapping_ref']}
    return row,refs


def prepare_current_r6_probes(paths, *, flags_ref, source_bundle_ref, signal_date, decision_as_of, current_report, run_dir):
    """Produce a small optional source; any missing coverage stays BLOCKED."""
    result=dict(schema=SCHEMA,status="BLOCKED",signal_date=signal_date,decision_as_of=decision_as_of,probe_ref=None,qualification_ref=None,flags_ref=flags_ref,source_bundle_ref=source_bundle_ref)
    try:
        day,observed=_scope(signal_date,decision_as_of)
        from scripts.common.storage_paths import assert_safe_output_path
        from scripts.research.a2.inference import consensus_paper as current
        from scripts.storage.storage_r2a import DataStore
        current.resource_check()  # Original physical/page floors, before prefix construction.
        _need(source_bundle_ref.get("sha256")==current.BUNDLE_SHA,"R6_CURRENT_ORIGINAL_POOL_REQUIRED")
        bundle=current.metadata(source_bundle_ref,{"prehistory_ref","prehistory_calendar_ref","pool_variant_id","selection_rule"})
        _need(bundle.get("pool_variant_id")=="TOP100" and bundle.get("selection_rule")=="MANAGER_COUNT_WEIGHT_SUM","R6_CURRENT_POOL_CHANGED")
        prior=_scan(bundle["prehistory_ref"],META,"signal_date","2023-01-01","2025-12-31")
        tail=_scan(flags_ref,META,"signal_date","2026-01-01",day)
        cal=_scan(bundle["prehistory_calendar_ref"],["trade_date"],"trade_date","2023-01-01","2025-12-31")
        calendar=pd.DatetimeIndex(pd.to_datetime(cal.trade_date)).append(pd.DatetimeIndex(pd.to_datetime(tail.signal_date).drop_duplicates().sort_values()))
        pred=pd.concat([prior,tail],ignore_index=True)
        keys=needed_probe_keys(pred,calendar,day)
        rehab_path=Path(run_dir)/"rehab_receipt.json"
        if not rehab_path.is_file() and current_report.get("report_path"):
            rehab_path=Path(current_report["report_path"]).parent/"rehab_receipt.json"
        rehab_ref=_ref(rehab_path);rehab=json.loads(rehab_path.read_text(encoding="utf-8"))
        _need(rehab.get("source")=="MOOMOO_OPEND_GET_REHAB" and rehab.get("target_date")==signal_date and rehab.get("status") in ("READY","PARTIAL"),"R6_CURRENT_REHAB_RECEIPT_REQUIRED")
        rows=[r for r in rehab.get("results",[]) if r.get("status")=="PASS"]
        _need(len({r['code'] for r in rows})==len(rows),"R6_CURRENT_DUPLICATE_REHAB_CODE")
        by_code={r['code']:r for r in rows}; source_refs={"flags":flags_ref,"pool":source_bundle_ref,"rehab_receipt":rehab_ref,"prehistory":bundle["prehistory_ref"],"calendar":bundle["prehistory_calendar_ref"],"event_window_owner":EVENT_OWNER,"current_probe_owner":_ref(__file__)}
        _verified(EVENT_OWNER)
        from scripts.research.a2.data.joint_input_binding import existing_event_functions
        apply,_=existing_event_functions(EVENT_OWNER['path'])
        store=DataStore(paths); values=[]; history_cache={};factor_cache={};diagnostics=[]
        positions={d:i for i,d in enumerate(calendar)}
        for ticker,part in keys.groupby('ticker',sort=True):
            selected=[]
            for q in part.itertuples():
                identity=pred.loc[pd.to_datetime(pred.signal_date).between(q.signal_date,q.label_mature_date)&pred.ticker.eq(ticker),'security_id']
                _need(len(identity)==7 and identity.astype(str).eq(str(q.security_id)).all(),'R6_CURRENT_ENDPOINT_SID_COVERAGE:'+ticker)
                # Historical receipt dates establish timeliness, never permission
                # to ignore an event now known in the original label window.
                current_row=by_code.get('US.'+ticker)
                _need(current_row is not None,'R6_CURRENT_REHAB_COVERAGE:'+ticker)
                current_fetched=_clock(current_row.get('fetched_at'))
                _need(day.tz_localize('America/New_York')+pd.Timedelta(hours=16)<=current_fetched<=observed,
                    'R6_CURRENT_FUTURE_OR_STALE_REHAB:'+ticker)
                current_events,current_factor=_factor_dates(current_row,ticker,factor_cache)
                _need(not ((current_events>q.execution_date)&(current_events<=q.label_mature_date)).any(),
                    'R6_CURRENT_CA_CLASSIFICATION_REQUIRED:'+ticker+':'+str(q.signal_date.date())+':CURRENT_REVISION')
                source_refs['current_rehab/'+ticker]=current_factor
                deadline=calendar[positions[q.signal_date]+7].tz_localize('America/New_York')+pd.Timedelta(hours=16)
                historical=_historical_rehab(paths,q,deadline,observed,history_cache)
                tag=ticker+'/'+str(q.signal_date.date())
                if historical is not None:
                    row,historical_refs=historical
                    for name,ref in historical_refs.items():source_refs['historical/'+tag+'/'+name]=ref
                    history_status='ACCEPTED_REHAB_OBSERVED_BEFORE_STRIDE_DEADLINE'
                else:
                    row=by_code.get('US.'+ticker)
                    _need(row is not None,'R6_CURRENT_REHAB_COVERAGE:'+ticker)
                    history_status='NO_ACCEPTED_REHAB_BEFORE_STRIDE_DEADLINE_CURRENT_OBSERVATION_ONLY'
                fetched=_clock(row.get('fetched_at'))
                minimum=(q.label_mature_date if historical is not None else day).tz_localize('America/New_York')+pd.Timedelta(hours=16)
                _need(minimum<=fetched<=observed,'R6_CURRENT_FUTURE_OR_STALE_REHAB:'+ticker)
                event_days,factor_ref=_factor_dates(row,ticker,factor_cache)
                _need(not ((event_days>q.execution_date)&(event_days<=q.label_mature_date)).any(),'R6_CURRENT_CA_CLASSIFICATION_REQUIRED:'+tag)
                source_refs['rehab/'+tag]=factor_ref
                selected.append((q,deadline,fetched,history_status))
            dates=set(part.execution_date.dt.strftime('%Y-%m-%d'))|set(part.label_mature_date.dt.strftime('%Y-%m-%d'))
            # Metadata, SID and selected CA coverage all pass before any open
            # is decoded; only the exact original predecessor endpoint closure.
            opens,clocks,refs=_raw_endpoints(store,ticker,dates,observed)
            for i,ref in enumerate(refs):source_refs['raw/'+ticker+'/'+str(i)]=ref
            quantity,bad,_=apply(part.rename(columns={'label_mature_date':'label_end_date'}),[])
            _need(not bad.any(),'R6_CURRENT_UNKNOWN_EVENT')
            for i,(q,deadline,fetched,history_status) in enumerate(selected):
                entry,end=str(q.execution_date.date()),str(q.label_mature_date.date())
                available=max(fetched,clocks[entry],clocks[end])
                diagnostics.append(dict(ticker=ticker,signal_date=str(q.signal_date.date()),mature_date=end,
                    original_deadline_utc=deadline.tz_convert('UTC').isoformat(),rehab_source_status=history_status,
                    observation_available_at=available.isoformat(),late_at_original_probe=bool(available>deadline)))
                y=float(opens[end])/float(opens[entry])*float(quantity[i])-1.
                _need(np.isfinite(y) and y>=-1,'R6_CURRENT_INVALID_TARGET')
                values.append(dict(signal_date=q.signal_date,ticker=ticker,security_id=str(q.security_id),label_mature_date=q.label_mature_date,
                    observation_available_at=available,feature_available=True,label_available=True,
                    account_event_unhandled=False,label_unsupported_common_event=False,label_coordinate=current_r6_label(),y_open5=y))
        columns=[*KEYS,'label_mature_date','observation_available_at','feature_available','label_available','account_event_unhandled','label_unsupported_common_event','label_coordinate','y_open5']
        frame=pd.DataFrame(values,columns=columns)
        frame['signal_date']=pd.to_datetime(frame.signal_date);frame['label_mature_date']=pd.to_datetime(frame.label_mature_date)
        frame['observation_available_at']=pd.to_datetime(frame.observation_available_at,utc=True)
        proof=dict(schema='CURRENT_R6_PROBE_QUALIFICATION_V1',candidate_id=CANDIDATE,status='READY',signal_date=signal_date,decision_as_of=decision_as_of,
            source_refs=source_refs,source_coverage='EXACT_ORIGINAL_COHORT_PREDECESSORS',source_complete=True,probe_rows=len(frame),
            probe_key_sha256=hashlib.sha256(keys.to_json(date_format='iso',orient='records').encode()).hexdigest(),
            label_coordinate=current_r6_label(),available_clock_policy='MAX_ACTUAL_ENDPOINT_OBSERVATIONS_AND_SELECTED_ACCEPTED_REHAB_FETCH_NO_BACKDATING',
            probe_observation_diagnostics=diagnostics,
            event_policy='NO_EVENT_WINDOWS_ONLY_UNCLASSIFIED_CURRENT_CA_BLOCKED',new_fit_count=0,future_unmatured_probe_outcomes_read=0,outcome_columns_in_model_features=0)
        token=hashlib.sha256(json.dumps(proof,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:20]
        output=paths.daily_root/'A2_consensus_paper/current_source'/signal_date/'r6_duration'
        assert_safe_output_path(output,kind='daily',paths=paths);output.mkdir(parents=True,exist_ok=True)
        path=output/('probes_'+token+'.parquet')
        if path.exists():pd.testing.assert_frame_equal(pd.read_parquet(path),frame)
        else:frame.to_parquet(path,index=False,compression='zstd')
        proof['probe_ref']=_ref(path)
        proof_ref=_save_immutable(output/('qualification_'+token+'.json'),proof)
        result.update(status='READY',probe_ref=proof['probe_ref'],qualification_ref=proof_ref)
    except Exception as exc:
        result['reason']=(type(exc).__name__+':'+str(exc))[:1024]
    return result


def current_r6_label():
    from scripts.research.a2.training.stateful_inputs import LABEL
    return LABEL


def validate_current_duration_frame(paths, *, frame, qualification, r6_probe_source, signal_date, decision_as_of):
    """Read-only existing frame/proof validation; no prefix/model recomputation."""
    day,observed=_scope(signal_date,decision_as_of)
    source=r6_probe_source
    _need(isinstance(source,dict) and source.get('schema')==SCHEMA and source.get('status')=='READY'
        and source.get('signal_date')==signal_date and _clock(source.get('decision_as_of'))==observed,'R6_CURRENT_QUALIFIED_PRODUCER_REQUIRED')
    proof=json.loads(_verified(source['qualification_ref']).read_text(encoding='utf-8'))
    _need(proof.get('schema')=='CURRENT_R6_PROBE_QUALIFICATION_V1' and proof.get('probe_ref')==source.get('probe_ref') and proof.get('candidate_id')==CANDIDATE
        and proof.get('status')=='READY' and proof.get('source_complete') is True and proof.get('signal_date')==signal_date
        and _clock(proof.get('decision_as_of'))==observed and proof.get('label_coordinate')==current_r6_label(),'R6_CURRENT_PROBE_PROOF_CHANGED')
    _verified(source['probe_ref'])
    _need(proof['source_refs'].get('flags')==source.get('flags_ref')
        and proof['source_refs'].get('pool')==source.get('source_bundle_ref'),'R6_CURRENT_BASE_SOURCE_CHANGED')
    for ref in proof['source_refs'].values():_verified(ref)
    state,_,_=_kernels(day)
    _need(qualification.get('original_source_pins')==state._PINS,'R6_CURRENT_ORIGINAL_KERNEL_CHANGED')
    _need(qualification.get('current_scope')=='SOURCE_BOUND_CURRENT_ONLY_NO_HISTORICAL_ADMISSION_INHERITED','R6_CURRENT_SCOPE_CHANGED')
    expected={**proof['source_refs'],'probe':source['probe_ref'],'probe_qualification':source['qualification_ref']}
    _need(qualification.get('source_refs')==expected,'R6_CURRENT_FRAME_SOURCES_CHANGED')
    for field in ('new_fit_count','future_unmatured_probe_outcomes_read','outcome_columns_in_model_features'):
        _need(type(qualification.get(field)) is int and qualification[field]==0 and type(proof.get(field)) is int and proof[field]==0,'R6_CURRENT_NONZERO_OR_UNKNOWN_COMPUTATION')
    mature=qualification.get('matured_probe_state',{})
    _need(mature.get('source_ref')==source['qualification_ref'] and mature.get('key_sha256')==proof.get('probe_key_sha256')
        and len(mature.get('key_sha256',''))==64 and all(c in '0123456789abcdef' for c in mature['key_sha256'])
        and _clock(mature.get('as_of_utc'))==observed and mature.get('causal_rule')=='previous_probe_mature_date < current_signal_date'
        and mature.get('prior_probe_mature_before_current_decision') is True,'R6_CURRENT_CAUSAL_PROBE_BINDING_CHANGED')
    _need(type(frame) is pd.DataFrame and not set(frame).intersection(state._OUTCOMES)
        and set(KEYS).issubset(frame) and pd.to_datetime(frame.signal_date).eq(day).all()
        and not frame.duplicated(['signal_date','sample_id']).any(),'R6_CURRENT_FRAME_IDENTITY_OR_OUTCOME')
    from scripts.research.a2.inference.frozen_a94_actions import input_commitment,role_features
    _need(qualification.get('input_commitment')==input_commitment(frame,role_features('R6:duration')),'R6_CURRENT_FRAME_COMMITMENT_CHANGED')
    return qualification


def build_current_duration_frame(paths, *, prediction_prefix, calendar_prefix, signal_date, decision_as_of, r6_probe_source):
    day,observed=_scope(signal_date,decision_as_of);cal=_calendar(calendar_prefix,day)
    source=r6_probe_source
    _need(isinstance(source,dict) and source.get('schema')==SCHEMA and source.get('status')=='READY'
        and source.get('signal_date')==signal_date and source.get('decision_as_of')==decision_as_of,'R6_CURRENT_QUALIFIED_PRODUCER_REQUIRED')
    proof=json.loads(_verified(source['qualification_ref']).read_text(encoding='utf-8'))
    _need(proof.get('schema')=='CURRENT_R6_PROBE_QUALIFICATION_V1' and proof.get('candidate_id')==CANDIDATE and proof.get('status')=='READY'
        and proof.get('source_complete') is True and proof.get('signal_date')==signal_date and proof.get('decision_as_of')==decision_as_of
        and proof.get('probe_ref')==source['probe_ref'] and proof.get('label_coordinate')==current_r6_label(),'R6_CURRENT_PROBE_PROOF_CHANGED')
    _need(proof['source_refs'].get('flags')==source.get('flags_ref')
        and proof['source_refs'].get('pool')==source.get('source_bundle_ref'),'R6_CURRENT_BASE_SOURCE_CHANGED')
    for ref in proof['source_refs'].values():_verified(ref)
    from scripts.research.a2.inference import consensus_paper as current
    current.resource_check()
    state,decision,build=_kernels(day)
    pred=prediction_prefix[list(state._PRED)].copy();pred['signal_date']=pd.to_datetime(pred.signal_date)
    _validate_structural_keys(pred,cal)
    structural,_=_projected_samples(build,pred,pd.DataFrame(columns=decision.LABEL_COLS),cal,day,'hold')
    hold=structural['hold']
    # Other objective surfaces have no consumer in this qualification phase.
    # Release them before the mature-probe replay, preserving the original
    # cohort transitions, full calendar, keys and final audit.
    del structural
    needed=_probe_keys_from_hold(hold,cal,day)
    probe=pd.read_parquet(_verified(source['probe_ref']))
    _need(proof.get('probe_key_sha256')==hashlib.sha256(needed.to_json(date_format='iso',orient='records').encode()).hexdigest()
        and len(probe)==len(needed) and set(map(tuple,probe[list(KEYS)].itertuples(index=False,name=None)))==set(map(tuple,needed[list(KEYS)].itertuples(index=False,name=None))), 'R6_CURRENT_PROBE_KEYS_CHANGED')
    cohort=state._empty(hold,(*KEYS,'cohort_age_sessions'))
    del hold
    mature,late=state._probes(probe,pred,day,observed,False,cohort,cal)
    del cohort,probe,needed
    import gc
    gc.collect()
    frames,audit=_projected_samples(build,pred,mature[list(decision.LABEL_COLS)],cal,day,'duration')
    base=(*KEYS,'sample_id',*decision.SINGLE,'cohort_id','probe_age')
    frame=state._clean(state._empty(frames['duration'],base),day)
    from scripts.research.a2.inference.frozen_a94_actions import input_commitment,role_features
    commitment=input_commitment(frame,role_features('R6:duration'))
    return dict(frame=frame,qualification=dict(input_commitment=commitment,
        matured_probe_state=dict(source_ref=source['qualification_ref'],key_sha256=proof['probe_key_sha256'],as_of_utc=observed.isoformat(),
            causal_rule='previous_probe_mature_date < current_signal_date',prior_probe_mature_before_current_decision=True),
        source_refs={**proof['source_refs'],'probe':source['probe_ref'],'probe_qualification':source['qualification_ref']},
        original_source_pins=dict(state._PINS),late_publication_metadata_discarded=late,cohort_audit=audit,
        current_scope='SOURCE_BOUND_CURRENT_ONLY_NO_HISTORICAL_ADMISSION_INHERITED',new_fit_count=0,future_unmatured_probe_outcomes_read=0,outcome_columns_in_model_features=0))
