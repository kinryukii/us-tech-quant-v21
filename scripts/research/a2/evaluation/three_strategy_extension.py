"""Independent descriptive PIT replay; never modifies frozen QFQ artifacts.

The caller supplies hash-qualified prices and recorded feature snapshots. Missing
signals stop the common window instead of silently skipping a session.
"""
from pathlib import Path
import hashlib
import json
import sys
import importlib.util
import ast
import inspect
import re
from io import BytesIO
from types import SimpleNamespace
from datetime import datetime, timezone

import numpy as np
import pandas as pd

IDS = ("RAW_A2", "HGB_DIAG_5", "HGB_FACTOR_5")
BASIS = "PIT_FORWARD_REHAB_INDEX"
E5_SOURCE_SHA = "005fdbc3a50df5552b4837e2706b7184198c1d1bfcfd7d51d03d3f3b55aabfa6"


class HeldPriceMissing(ValueError):
    def __init__(self, signal, execution, keys):
        self.signal, self.execution, self.keys = signal, execution, keys
        super().__init__("HELD_EXECUTION_PRICE_MISSING:" + json.dumps(keys))


class HeldEventUnresolved(HeldPriceMissing):
    pass


def reference(path):
    path = Path(path).resolve()
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path), "sha256": digest}


def _write_extension_manifest(path, manifest):
    """Return the exact JSON object published, including partial gap keys."""
    payload = json.dumps(manifest, ensure_ascii=False, allow_nan=False, indent=2)
    published = json.loads(payload)
    Path(path).write_text(payload, encoding="utf-8")
    return published


def verify_refs(refs):
    seen = {}
    for ref in refs:
        path = str(Path(ref["path"]).resolve())
        if path in seen and seen[path] != ref["sha256"]:
            raise ValueError("CONFLICTING_SOURCE_HASH:" + path)
        if reference(path)["sha256"] != ref["sha256"]:
            raise ValueError("SOURCE_HASH_MISMATCH:" + path)
        seen[path] = ref["sha256"]


def _freeze_producer_vintage(output_dir, observation, data):
    """Preserve exact producing bytes in this existing run, never a mutable source ref."""
    if hashlib.sha256(data).hexdigest() != observation["sha256"]:
        raise ValueError("PRODUCER_CAPTURE_HASH_MISMATCH")
    verify_refs([observation])
    destination = Path(output_dir) / "producer_source.py"
    if destination.resolve() == Path(observation["path"]).resolve():
        raise ValueError("OUTPUT_MUST_NOT_MUTATE_PRODUCER_SOURCE")
    with destination.open("xb") as stream:
        stream.write(data)
    frozen = reference(destination)
    if frozen["sha256"] != observation["sha256"]:
        raise ValueError("PRODUCER_VINTAGE_HASH_MISMATCH")
    verify_refs([observation, frozen])
    return frozen


def capture_full_prices(output_dir, *, repo_root="D:/us-tech-quant", current_report_path=None,
                        execution_open_manifest=None, execution_end=None, reuse_capture=None, prior_research_manifest=None):
    """Read or explicitly extend the existing hash-qualified execution capture."""
    sys.path.insert(0, str(Path(repo_root)))
    from scripts.common.storage_paths import resolve
    from scripts.research.a2.portfolio import selected_hgb as selected
    from scripts.research.a2.evaluation.demo_performance import canonical_manifest
    from scripts.research.a2.evaluation.demo_performance_prices import load_execution_prices
    from scripts.research.a2.evaluation.demo_performance import reviewed_events
    paths = resolve(Path(repo_root))
    if prior_research_manifest is not None:
        if reuse_capture is not None:
            raise ValueError("PRIOR_RESEARCH_AND_SAME_PHASE_CAPTURE_CONFLICT")
        result, metadata = _advance_research_capture(paths, prior_research_manifest,
            current_report_path, execution_open_manifest, execution_end)
        resolved = metadata["event_review_resolved"]
    elif reuse_capture is not None:
        result, metadata = _reuse_execution_open_capture(paths, reuse_capture,
            current_report_path, execution_open_manifest, execution_end)
        resolved = metadata["event_review_resolved"]
    else:
        historical, _ = canonical_manifest(Path(paths.daily_root) / "A2_historical_top40/latest.json")
        hist = json.loads(historical.read_text(encoding="utf-8"))
        top_ref = hist["outputs"]["top40"]
        verify_refs([top_ref])
        tickers = set(pd.read_parquet(top_ref["path"], columns=["ticker"]).ticker)
        frames, feature_refs = load_sources(paths, selected, selected.DEFAULT_SOURCE_ROOT)
        for frame in frames:
            tickers.update(frame.ticker.astype(str))
        updated, _ = canonical_manifest(Path(paths.daily_root) / "A2_updated_research/latest.json")
        update = json.loads(updated.read_text(encoding="utf-8"))
        rank_ref = update["outputs"]["rankings"]
        verify_refs([rank_ref])
        tickers.update(pd.read_parquet(rank_ref["path"], columns=["ticker"]).ticker.astype(str))
        if current_report_path is None:
            latest = json.loads((Path(paths.daily_root) / "A2_today_recommendation/latest.json").read_text(encoding="utf-8"))
            current_report_path = latest.get("performance_update", {}).get("source_report") or latest["report_path"]
        current_report_path = Path(current_report_path)
        report = json.loads(current_report_path.read_text(encoding="utf-8"))
        result = load_execution_prices(paths, historical, tickers=sorted(tickers),
            current_report_path=current_report_path, start="2023-01-03", end=report["data_date"],
            **({"execution_open_manifest": execution_open_manifest, "execution_end": execution_end}
               if execution_open_manifest is not None or execution_end is not None else {}))
        resolved, audit = reviewed_events(result["events"], result.get("event_review"), result.get("refs", []))
        metadata = {key: value for key, value in result.items() if key not in {"prices", "events"}}
        metadata["refs"].extend([top_ref, rank_ref, reference(updated), reference(historical), reference(current_report_path), *feature_refs])
        verify_refs(metadata["refs"])
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    price_path, input_path = output / "three_strategy_prices.parquet", output / "three_strategy_price_inputs.json"
    if price_path.exists() or input_path.exists():
        raise ValueError("CAPTURE_ALREADY_EXISTS_USE_FRESH_DIRECTORY")
    result["prices"].to_parquet(price_path, index=False)
    metadata["captured_prices"] = reference(price_path)
    event_path = output / "three_strategy_events.parquet"
    if event_path.exists():
        raise ValueError("EVENT_CAPTURE_ALREADY_EXISTS")
    result["events"].to_parquet(event_path, index=False)
    metadata["events"] = reference(event_path)
    metadata["event_review_resolved"] = bool(resolved)
    input_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return price_path, input_path


def _bound_selected_research(paths, prior_ref=None):
    """Bind canonical/strict base-bound display research through existing owners."""
    from scripts.research.a2.portfolio import selected_hgb as selected
    from scripts.research.a2.evaluation.selected_performance_update import verified_selected_research
    from apps.demo_console.adapters import selected_strategies_reader as reader
    policy, path = selected.active_policy(paths)
    if policy not in {selected.DIRECT_POLICY, selected.LEGACY_POLICY}:
        raise ValueError("PRIOR_SELECTED_POLICY_REQUIRED")
    base, observation = _capture_json(path)
    reader.validate_package(base)
    if base.get("policy_id", selected.LEGACY_POLICY) != policy:
        raise ValueError("PRIOR_RESEARCH_ACTIVE_POLICY_CHANGED")
    package = base
    canonical_ref = base["performance_extension"]["manifest"]
    if prior_ref is None or prior_ref != canonical_ref:
        observed = reader.load_package()
        if (Path(observed["package_path"]).resolve() != Path(path).resolve()
                or observed["package_sha256"] != observation["sha256"]
                or observed.get("policy_id", selected.LEGACY_POLICY) != policy):
            raise ValueError("PRIOR_RESEARCH_CANONICAL_OBSERVATION_CHANGED")
        package = observed
    if policy == selected.DIRECT_POLICY:
        from scripts.research.a2.evaluation.hgb_policy_alignment import frozen_contract
        task, _ = frozen_contract(paths)
        contract = task["frozen_contract"]
        if (package["source_refs"].get("policy/frozen_contract") != contract
                or package["source_hashes"].get("policy/frozen_contract") != contract["sha256"]):
            raise ValueError("PRIOR_RESEARCH_POLICY_CONTRACT_UNBOUND")
    manifest, manifest_ref = verified_selected_research(package)
    if prior_ref is not None and manifest_ref != prior_ref:
        raise ValueError("PRIOR_RESEARCH_IMMUTABLE_SELECTION_CHANGED")
    verify_refs([observation])
    return package, manifest, manifest_ref, observation


def bound_direct_research(paths, prior_ref=None):
    """Retain the original DIRECT-only interface and frozen-contract binding."""
    from scripts.research.a2.portfolio import selected_hgb as selected
    if selected.active_policy(paths)[0] != selected.DIRECT_POLICY:
        raise ValueError("PRIOR_DIRECT_POLICY_REQUIRED")
    return _bound_selected_research(paths, prior_ref)


def bound_selected_research(paths, prior_ref=None):
    """Select the existing same-policy binder without relaxing the direct gate."""
    from scripts.research.a2.portfolio import selected_hgb as selected
    if selected.active_policy(paths)[0] == selected.DIRECT_POLICY:
        return bound_direct_research(paths, prior_ref)
    return _bound_selected_research(paths, prior_ref)


def prior_price_capture(manifest):
    """Select the single leaf of the accepted capture lineage, never by file order."""
    nodes = {}
    for ref in manifest["source_refs"]:
        if Path(ref["path"]).name not in {"three_strategy_price_inputs.json", "price_inputs.json"}:
            continue
        value, captured = _capture_json(ref["path"], ref["sha256"])
        if value.get("price_basis") != BASIS or value.get("captured_prices") not in manifest["source_refs"]:
            continue
        if value.get("events") not in manifest["source_refs"] or value.get("event_review_resolved") is not True:
            raise ValueError("PRIOR_PRICE_EVENT_BINDING_INVALID")
        nodes[(captured["path"], captured["sha256"])] = (captured, value)
    parents = {(ref["path"], ref["sha256"]) for _, value in nodes.values()
               for ref in [value.get("capture_reuse", {}).get("inputs_ref")]
               if ref is not None}
    leaves = [item for key, item in nodes.items() if key not in parents]
    if len(leaves) != 1 or not parents.issubset(set(nodes)):
        raise ValueError("PRIOR_PRICE_CAPTURE_IDENTITY_AMBIGUOUS")
    ref, metadata = leaves[0]
    verify_refs([ref, metadata["captured_prices"], metadata["events"], *metadata["refs"]])
    return ref, metadata



def _prior_open_maturity(old, old_prices, prior_end, fresh, report, historical):
    """Only an accepted open-only tail may mature, under unchanged identities."""
    phase = old.get("execution_open")
    if not phase:
        if old_prices[["close","high","low","volume"]].isna().any().any():
            raise ValueError("PRIOR_PRICE_UNKNOWN_FIELD_WITHOUT_OPEN_PHASE")
        return set(), []
    ref = phase.get("manifest")
    if (ref not in old["refs"] or phase.get("execution_end_date") != prior_end
            or phase.get("signal_end_date") != old["end_date"] or phase.get("consumer_fields") != ["open"]
            or phase.get("terminal_close_available") is not False
            or phase.get("model_feature_eligibility_granted") is not False):
        raise ValueError("PRIOR_PRICE_MATURITY_PHASE_UNBOUND")
    document, _ = _capture_json(ref["path"],ref["sha256"])
    if (document.get("schema") != "A2_EXECUTION_OPEN_INPUTS_V1"
            or document.get("execution_end_date") != prior_end
            or document.get("signal_end_date") != phase["signal_end_date"]):
        raise ValueError("PRIOR_PRICE_MATURITY_PHASE_CLOCK_CHANGED")
    def records(value):
        rows = value.get("records", [])
        mapped = {row["ticker"]:row for row in rows}
        if (not rows or len(mapped) != len(rows)
                or any(not all(row.get(key) for key in ("ticker","code","security_id")) for row in rows)):
            raise ValueError("PRIOR_PRICE_MATURITY_IDENTITY_RECORDS_INVALID")
        return mapped
    prior_records = records(document)
    qualified = phase.get("qualified_tickers",[])
    proof = phase.get("qualifications",[])
    if (len(set(qualified)) != len(qualified) or not qualified
            or not set(qualified).issubset(prior_records)
            or sorted(row["ticker"] for row in proof) != sorted(qualified)
            or any(row.get("all_overlap_open_exact") is not True
                   or row.get("preserved_original_raw_vintage") is not True for row in proof)):
        raise ValueError("PRIOR_PRICE_MATURITY_ORIGINAL_QUALIFICATION_MISSING")
    terminal = old_prices.loc[old_prices.trade_date.eq(pd.Timestamp(prior_end)) & old_prices.ticker.isin(qualified)]
    if (len(terminal) != len(qualified) or set(terminal.ticker) != set(qualified)
            or not terminal[["close","high","low","volume"]].isna().all().all()
            or not np.isfinite(terminal.open).all() or not terminal.open.gt(0).all()):
        raise ValueError("PRIOR_PRICE_MATURITY_REQUIRES_ORIGINAL_OPEN_ONLY")
    universe = report["universe"]
    mapped_ref = {"path":str((Path(universe["report_path"]).parent/"mapped_members.parquet").resolve()),
                  "sha256":universe["universe_members_sha256"]}
    verify_refs([mapped_ref])
    import pyarrow.parquet as pq
    members = pq.read_table(mapped_ref["path"],columns=["ticker","moomoo_symbol","security_id"]).to_pandas()
    member_keys = {(str(row.ticker),str(row.moomoo_symbol),str(row.security_id)) for row in members.itertuples(index=False)}
    member_names = set(members.ticker)
    refs = [ref,mapped_ref]
    next_phase = fresh.get("execution_open")
    new_records = None
    if next_phase:
        next_ref = next_phase["manifest"]
        if next_ref not in fresh["refs"]:
            raise ValueError("PRIOR_PRICE_MATURITY_NEW_PHASE_UNBOUND")
        next_document,_ = _capture_json(next_ref["path"],next_ref["sha256"])
        new_records = records(next_document)
        if next_document.get("identity_binding",{}).get("sha256") != mapped_ref["sha256"]:
            raise ValueError("PRIOR_PRICE_MATURITY_CURRENT_IDENTITY_AUTHORITY_CHANGED")
        refs.append(next_ref)
    historical_rows = None
    for name in qualified:
        row = prior_records[name]
        triple = (name,str(row["code"]),str(row["security_id"]))
        if new_records is not None and new_records.get(name) != row:
            raise ValueError("PRIOR_PRICE_MATURITY_SECURITY_IDENTITY_CHANGED:"+name)
        if triple in member_keys:
            continue
        if name in member_names:
            raise ValueError("PRIOR_PRICE_MATURITY_CURRENT_SECURITY_IDENTITY_CHANGED:"+name)
        # Preserve the original held-name fallback; current membership is not a gate.
        if historical_rows is None:
            hist,_ = _capture_json(historical)
            hist_ref = hist["price_manifest"]
            if document.get("historical_identity_binding") != hist_ref:
                raise ValueError("PRIOR_PRICE_MATURITY_HISTORICAL_IDENTITY_UNBOUND")
            value,_ = _capture_json(hist_ref["path"],hist_ref["sha256"])
            historical_rows = value["lineage"];refs.append(hist_ref)
        matches = [entry for entry in historical_rows if entry.get("ticker") == name
                   and entry.get("code") == row["code"] and entry.get("cusips") == [row["security_id"]]]
        if len(matches) != 1:
            raise ValueError("PRIOR_PRICE_MATURITY_HISTORICAL_SECURITY_IDENTITY_CHANGED:"+name)
    verify_refs(refs)
    return {(name,pd.Timestamp(prior_end)) for name in qualified},refs

def _accepted_field_origin_proof(old, fresh, report_path, historical, prior_end,
                                 before, incoming, tickers, field_keys, capture_ref):
    """Trace only changed, already accepted fields through immutable capture links."""
    from scripts.research.a2.evaluation.demo_performance_prices import PRICE_COLUMNS
    scope = {(ref["path"],ref["sha256"]) for ref in old["refs"]}
    refs, visited, groups = [], set(), {}
    indexed = before.set_index(["ticker","trade_date"])
    pending = {tuple(key):float(indexed.at[key[:2],key[2]]) for key in field_keys}
    if not pending: raise ValueError("VINTAGE_FIELD_ORIGIN_EMPTY")
    # The bound finite graph, not an arbitrary day count, bounds traversal.
    node, node_ref = old, capture_ref
    for _ in range(1 + len(scope)):
        reuse = node.get("capture_reuse")
        parent_ref = reuse.get("inputs_ref") if isinstance(reuse,dict) else None
        if reuse is not None and (not isinstance(reuse,dict) or parent_ref is None
                or not isinstance(reuse.get("prices_ref"),dict)
                or not (reuse.get("known_price_fields_all_exact") is True
                        or reuse.get("existing_prices_all_fields_exact") is True
                        and reuse.get("existing_event_audit_exact") is True
                        and reuse.get("parent_execution_open_manifest") in node.get("refs",[]))):
            raise ValueError("VINTAGE_FIELD_ORIGIN_PARENT_MISSING")
        if parent_ref is None:
            inherited = {}
        else:
            identity = (parent_ref.get("path"),parent_ref.get("sha256"))
            if identity in visited: raise ValueError("VINTAGE_FIELD_ORIGIN_CYCLE")
            if identity not in scope or parent_ref not in node.get("refs",[]):
                raise ValueError("VINTAGE_FIELD_ORIGIN_PARENT_UNBOUND")
            visited.add(identity)
            parent, checked = _capture_json(parent_ref["path"],parent_ref["sha256"])
            price_ref = reuse["prices_ref"]
            # Captured files can contain unconsumed future tails. A closed
            # field is inherited only inside this parent's accepted interval.
            end = parent.get("end_date")
            if not isinstance(end,str) or len(end) != 10:
                raise ValueError("VINTAGE_FIELD_ORIGIN_PARENT_BINDING_CHANGED")
            try:
                parent_end = pd.Timestamp(end)
            except (TypeError,ValueError) as exc:
                raise ValueError("VINTAGE_FIELD_ORIGIN_PARENT_BINDING_CHANGED") from exc
            if pd.isna(parent_end) or parent_end.tzinfo is not None or parent_end.strftime("%Y-%m-%d") != end:
                raise ValueError("VINTAGE_FIELD_ORIGIN_PARENT_BINDING_CHANGED")
            whole_capture = reuse.get("reused_accepted_closed_capture") is True
            whole_open_capture = (reuse.get("existing_prices_all_fields_exact") is True
                and reuse.get("existing_event_audit_exact") is True
                and isinstance(reuse.get("parent_execution_open_manifest"),dict)
                and reuse["parent_execution_open_manifest"] in node.get("refs",[]))
            if whole_capture:
                if node.get("captured_prices",{}).get("sha256") != price_ref.get("sha256"):
                    raise ValueError("VINTAGE_FIELD_ORIGIN_WHOLE_CAPTURE_CHANGED")
            elif not whole_open_capture:
                # Normal advance preserves only the prior replay's consumed
                # prefix; older captures can own unused, replaceable tails.
                owner_ref = node.get("research_input_owner")
                if (not isinstance(owner_ref,dict) or owner_ref not in node.get("refs",[])
                        or (owner_ref.get("path"),owner_ref.get("sha256")) not in scope):
                    raise ValueError("VINTAGE_FIELD_ORIGIN_OWNER_UNBOUND")
                owner, owner_checked = _capture_json(owner_ref["path"],owner_ref["sha256"])
                from scripts.research.a2.evaluation.selected_performance_update import research_policy
                from scripts.research.a2.portfolio import selected_hgb as selected
                limit = owner.get("performance_period",{}).get("end")
                if (research_policy(owner,owner_checked) != selected.LEGACY_POLICY
                        or parent_ref not in owner.get("source_refs",[])
                        or price_ref not in owner.get("source_refs",[])
                        or not isinstance(limit,str) or len(limit) != 10):
                    raise ValueError("VINTAGE_FIELD_ORIGIN_OWNER_BINDING_CHANGED")
                try:
                    consumed_end = pd.Timestamp(limit)
                except (TypeError,ValueError) as exc:
                    raise ValueError("VINTAGE_FIELD_ORIGIN_OWNER_BINDING_CHANGED") from exc
                if (pd.isna(consumed_end) or consumed_end.tzinfo is not None
                        or consumed_end.strftime("%Y-%m-%d") != limit or consumed_end > parent_end):
                    raise ValueError("VINTAGE_FIELD_ORIGIN_OWNER_BINDING_CHANGED")
                refs.append(owner_checked)
                parent_end = min(parent_end,consumed_end)
            eligible = {key for key in pending if key[1] <= parent_end}
            names = {key[0] for key in eligible}
            gaps = parent.get("gaps",[])
            if (parent.get("captured_prices") != price_ref or price_ref not in node.get("refs",[])
                    or parent.get("price_basis") != BASIS or parent.get("event_review_resolved") is not True
                    or not isinstance(gaps,list)
                    or any(not isinstance(gap,dict) or not isinstance(gap.get("ticker"),str)
                           or not gap["ticker"] or gap["ticker"] in names for gap in gaps)
                    or parent.get("start_date") != node.get("start_date")
                    or parent.get("end_date","") > node.get("end_date","")):
                raise ValueError("VINTAGE_FIELD_ORIGIN_PARENT_BINDING_CHANGED")
            refs.extend([checked,price_ref])
            keys = {key[:2] for key in eligible}; dates = [key[1] for key in keys]
            if keys:
                frame = _capture_parquet(price_ref,columns=PRICE_COLUMNS,date_column="trade_date",
                    start=min(dates),stop=max(dates)+pd.Timedelta(days=1),price_keys=keys)
                frame["trade_date"] = pd.to_datetime(frame.trade_date)
            else:
                frame = pd.DataFrame(columns=PRICE_COLUMNS)
            frame = frame.set_index(["ticker","trade_date"])
            if not frame.index.is_unique: raise ValueError("VINTAGE_FIELD_ORIGIN_DUPLICATE_KEY")
            inherited = {}
            for key,value in pending.items():
                if key not in eligible or key[:2] not in frame.index or pd.isna(frame.at[key[:2],key[2]]): continue
                if frame.at[key[:2],key[2]] != value:
                    raise ValueError("VINTAGE_FIELD_ORIGIN_KNOWN_FIELD_CHANGED:"+key[0]+":"+str(key[1].date())+":"+key[2])
                inherited[key] = value
            audit = reuse.get("accepted_closed_vintage_continuation",{})
            audited = {}
            for row in audit.get("field_differences",[]):
                key=(row["ticker"],pd.Timestamp(row["trade_date"]),row["field"])
                if key in audited: raise ValueError("VINTAGE_FIELD_ORIGIN_AUDIT_DUPLICATE")
                audited[key]=row
            for key,value in pending.items():
                if key in audited and (key not in inherited
                        or audited[key].get("accepted_value") != value
                        or not np.isfinite(float(audited[key].get("incoming_value",np.nan)))):
                    raise ValueError("VINTAGE_FIELD_ORIGIN_AUDIT_CHANGED")
        local = [key for key in pending if key not in inherited]
        if local:
            label = (node_ref["path"],node_ref["sha256"]) if node_ref else ("accepted-current","")
            groups.setdefault(label,{"metadata":node,"capture_ref":node_ref,"keys":[]})["keys"].extend(local)
        if not inherited: break
        pending, node, node_ref = inherited, parent, checked
    else: raise ValueError("VINTAGE_FIELD_ORIGIN_GRAPH_NOT_CLOSED")
    # Keep the original full history-key gate before field-origin projection.
    for name in tickers:
        x=before.loc[before.ticker.eq(name),"trade_date"]
        y=incoming.loc[incoming.ticker.eq(name)&incoming.trade_date.le(pd.Timestamp(prior_end)),"trade_date"]
        if set(x)!=set(y) or len(x)!=len(y): raise ValueError("VINTAGE_OLD_HISTORY_KEYS_CHANGED:"+name)
    proofs, origins = [], []
    for group in groups.values():
        keys=set(key[:2] for key in group["keys"])
        def project(frame):
            return frame.loc[[key in keys for key in zip(frame.ticker,pd.to_datetime(frame.trade_date))]].copy()
        proof=_accepted_closed_vintage_proof(group["metadata"],fresh,report_path,historical,prior_end,
            project(before),project(incoming),{key[0] for key in group["keys"]},_origin_scope=True)
        proofs.append(proof);refs.extend(proof["source_refs"])
        origins.append({"capture_ref":group["capture_ref"],
            "prices_ref":group["metadata"]["captured_prices"],"accepted_report":proof["accepted_report"],
            "fields":[{"ticker":key[0],"trade_date":str(key[1].date()),"field":key[2]}
                      for key in sorted(group["keys"])]})
    verify_refs(refs)
    return {**proofs[0],"ticker_proofs":[row for proof in proofs for row in proof["ticker_proofs"]],
        "source_refs":refs,"accepted_field_origins":origins}


def _accepted_closed_vintage_proof(old, fresh, report_path, historical, prior_end, before, incoming, tickers,
                                   *, existing_candidate_tail=False, accepted_candidates=None,
                                   _origin_scope=False, _field_keys=None, _capture_ref=None):
    """Qualify two recorded RAW vintages in one unchanged forward coordinate."""
    if not existing_candidate_tail and old.get("capture_reuse") is not None and not _origin_scope:
        return _accepted_field_origin_proof(old,fresh,report_path,historical,prior_end,
            before,incoming,tickers,_field_keys or [],_capture_ref)
    from scripts.research.a2.evaluation import demo_performance_prices as reader
    from scripts import daily_recommendation_prices as original
    import pyarrow.parquet as pq
    from scripts.research.a2.portfolio import selected_hgb as selected
    refs = []
    def bind(path, expected):
        ref = {"path": str(Path(path).resolve()), "sha256": expected}
        verify_refs([ref]); refs.append(ref); return Path(ref["path"])
    historical_ref = reference(historical)
    if historical_ref not in old["refs"] or historical_ref not in fresh["refs"]:
        raise ValueError("VINTAGE_HISTORICAL_AUTHORITY_UNBOUND")
    try:
        origin_end = selected._date(old.get("end_date"))
        outer_end = selected._date(prior_end)
    except (TypeError, ValueError) as exc:
        raise ValueError("VINTAGE_ORIGIN_CLOCK_INVALID") from exc
    candidates = []
    for ref in old["refs"]:
        if Path(ref["path"]).name in {"recommendation_source.json", "report.json"}:
            value, _ = _capture_json(ref["path"], ref["sha256"])
            if value.get("status") == "READY" and value.get("data_date") == old["end_date"]:
                candidates.append(ref)
    candidates = list({(ref["path"], ref["sha256"]): ref for ref in candidates}.values())
    if len(candidates) != 1:
        raise ValueError("VINTAGE_PRIOR_REPORT_AMBIGUOUS")
    old_ref = candidates[0]; new_ref = reference(report_path)
    if new_ref not in fresh["refs"]:
        raise ValueError("VINTAGE_CURRENT_REPORT_UNBOUND")
    hist_sha = historical_ref["sha256"]
    old_entries, old_report = reader._current_entries(old_ref["path"], Path(historical).resolve(), hist_sha, bind)
    new_entries, new_report = reader._current_entries(report_path, Path(historical).resolve(), hist_sha, bind)
    try:
        report_origin_end = selected._date(old_report.get("data_date"))
    except (TypeError, ValueError) as exc:
        raise ValueError("VINTAGE_ORIGIN_CLOCK_INVALID") from exc
    if report_origin_end != origin_end:
        raise ValueError("VINTAGE_ORIGIN_CLOCK_UNBOUND")
    # Field-origin recursion retains the outer closed ledger end. Only facts
    # already dated at this bound origin can qualify its accepted price fields.
    factor_end = min(outer_end, origin_end)
    if (old.get("price_basis") != BASIS or fresh.get("price_basis") != BASIS
            or old_report["data_date"] > new_report["data_date"]):
        raise ValueError("VINTAGE_PRICE_COORDINATE_OR_CLOCK_CHANGED")
    def members(report):
        universe = report["universe"]
        ref = {"path":str((Path(universe["report_path"]).parent/"mapped_members.parquet").resolve()),
               "sha256":universe["universe_members_sha256"]}
        frame = pq.read_table(bind(ref["path"],ref["sha256"]),
                              columns=["ticker","moomoo_symbol","security_id"]).to_pandas()
        if frame.ticker.duplicated().any(): raise ValueError("VINTAGE_DUPLICATE_MAPPED_IDENTITY")
        return frame.set_index("ticker")
    old_members, new_members = members(old_report), members(new_report)
    historical_doc, _ = _capture_json(historical, hist_sha)
    historical_inputs = historical_doc["price_manifest"]
    hist, _ = _capture_json(bind(historical_inputs["path"], historical_inputs["sha256"]))
    def identity(name, code, mapping):
        if name in mapping.index:
            row = mapping.loc[name]
            if row.moomoo_symbol != code or not isinstance(row.security_id,str) or not row.security_id:
                raise ValueError("VINTAGE_SECURITY_IDENTITY_CHANGED:"+name)
            return row.security_id
        rows = [row for row in hist["lineage"] if row.get("ticker") == name and row.get("code") == code]
        if len(rows) != 1 or len(rows[0].get("cusips",[])) != 1:
            raise ValueError("VINTAGE_HELD_IDENTITY_UNBOUND:"+name)
        return rows[0]["cusips"][0]
    def factors(entry):
        ref = entry["rehab"]; bind(ref["path"],ref["sha256"])
        footer = pq.ParquetFile(ref["path"])
        required = {"code","ex_div_date","forward_adj_factorA","forward_adj_factorB"}
        if not required <= set(footer.schema_arrow.names):
            raise ValueError("VINTAGE_REHAB_FACTOR_SCHEMA_CHANGED")
        frame = (_capture_parquet(ref) if footer.metadata.num_rows == 0 else
                 _capture_parquet(ref,date_column="ex_div_date",start=entry["anchor_date"],
                                  stop=pd.Timestamp(factor_end)+pd.Timedelta(days=1)))
        if len(frame) and not frame.code.eq(entry["code"]).all():
            raise ValueError("VINTAGE_REHAB_CODE_CHANGED")
        frame = frame.loc[frame.code.eq(entry["code"])].copy()
        frame["ex_div_date"] = pd.to_datetime(frame.ex_div_date)
        return frame.reset_index(drop=True)
    native_bounds = {}
    def native_readable(ref, report):
        # The original native validator reads whole bound files. Prove their
        # physical date scope first; never read a future price and then filter.
        path = bind(ref["path"],ref["sha256"])
        key = (str(path),ref["sha256"])
        if key not in native_bounds:
            try:
                if path.suffix.lower() == ".parquet":
                    footer = pq.ParquetFile(path)
                    column = next((name for name in ("trade_date","date","time_key")
                                   if name in footer.schema_arrow.names),None)
                    if column is None or footer.metadata.num_rows == 0:
                        raise ValueError("native source date schema is empty or absent")
                    index = footer.schema_arrow.names.index(column)
                    stats = [footer.metadata.row_group(i).column(index).statistics
                             for i in range(footer.metadata.num_row_groups)]
                    import pyarrow as pa
                    kind = footer.schema_arrow.field(column).type
                    # String footer endpoints are lexical, not chronological.
                    if ((pa.types.is_date(kind) or pa.types.is_timestamp(kind)) and
                            all(item is not None and item.has_min_max and item.null_count == 0 for item in stats)):
                        dates = pd.to_datetime([value for item in stats for value in (item.min,item.max)])
                    else:
                        dates = pd.to_datetime(pq.read_table(path,columns=[column]).column(column).to_pandas())
                elif path.suffix.lower() == ".csv":
                    columns = pd.read_csv(path,nrows=0).columns
                    column = next((name for name in ("trade_date","date","time_key") if name in columns),None)
                    if column is None: raise ValueError("native source date column absent")
                    bounds = []
                    for part in pd.read_csv(path,usecols=[column],chunksize=50000):
                        dates = pd.to_datetime(part[column])
                        if dates.isna().any(): raise ValueError("native source date missing")
                        bounds.extend([dates.min(),dates.max()])
                    dates = pd.DatetimeIndex(bounds)
                else: raise ValueError("native source date format unsupported")
                if len(dates) == 0 or pd.isna(dates).any(): raise ValueError("native source dates unbound")
                native_bounds[key] = (pd.Timestamp(dates.min()).normalize(),pd.Timestamp(dates.max()).normalize())
            except (ValueError,TypeError,KeyError,StopIteration) as exc:
                raise ValueError("VINTAGE_NATIVE_SOURCE_DATE_UNBOUND:"+name) from exc
        start,end = native_bounds[key]
        if end > pd.Timestamp(report["data_date"]):
            raise ValueError("VINTAGE_NATIVE_SOURCE_FUTURE_DATE:"+name)
        return {"source":ref,"physical_min_date":str(start.date()),"physical_max_date":str(end.date())}
    def adapter_binding(entry, report):
        fields = ("adapter_sha256", "coverage_manifest_sha256")
        native = entry.get("anchor_proof", {})
        if native.get("kind") == "NEW_13F_MEMBER_NATIVE_RAW_ANCHOR":
            # Original native current inference has its own recorded schema;
            # it neither emits an expanded manifest nor claims frozen equivalence.
            if (not existing_candidate_tail or any(key in entry for key in fields)
                    or "expanded_anchor_manifest" in entry
                    or native.get("scope") != "2026_INFERENCE_ONLY"
                    or native.get("old_frozen_equivalence_claimed") is not False
                    or entry.get("membership_validation") != "CALLER_VERIFIED_CURRENT_PIT_UNIVERSE"
                    or not entry.get("security_id")
                    or entry.get("security_ids") != [entry["security_id"]]
                    or entry.get("observed_target") != report["data_date"]
                    or not "2026-01-01" <= report["data_date"] < "2027-01-01"
                    or entry.get("vintage_semantics") != "LATER_VENDOR_RETRIEVAL_NOT_HISTORICAL_PUBLICATION_VINTAGE"):
                raise ValueError("VINTAGE_NATIVE_SCHEMA_OR_SCOPE_UNBOUND:"+entry["ticker"])
            feature = entry.get("feature_source", {})
            if feature.get("artifact_id") != "source" or not feature.get("path") or not feature.get("sha256"):
                raise ValueError("VINTAGE_NATIVE_FEATURE_SOURCE_UNBOUND:"+entry["ticker"])
            feature_ref = {"path":str(bind(feature["path"],feature["sha256"])), "sha256":feature["sha256"]}
            adapter = {"path":str(original.ADAPTER_PATH.resolve()), "sha256":original.ADAPTER_SHA}
            coverage = {"path":str(original.COVERAGE_PATH.resolve()), "sha256":original.COVERAGE_SHA}
            for item in (adapter,coverage): bind(item["path"],item["sha256"])
            return {"schema":"NATIVE_MOOMOO_ANCHOR", "adapter":adapter, "coverage":coverage,
                "implementation_refs":[feature_ref], "old_frozen_equivalence_claimed":False}
        if any(key in entry for key in fields):
            if (entry.get(fields[0]) != original.ADAPTER_SHA
                    or entry.get(fields[1]) != original.COVERAGE_SHA):
                raise ValueError("VINTAGE_ANCHOR_OR_ADAPTER_CHANGED:"+entry["ticker"])
            return None
        # Original expanded lineage records the same fixed authority in its
        # immutable manifest rather than duplicating two hashes per ticker.
        ref = entry.get("expanded_anchor_manifest")
        expected_path = (Path(report["report_path"]).resolve().parent /
                         "expanded_anchor_inputs/prices/manifest.json").resolve()
        if not isinstance(ref, dict) or Path(ref.get("path", "")).resolve() != expected_path:
            raise ValueError("VINTAGE_EXPANDED_MANIFEST_UNBOUND:"+entry["ticker"])
        doc, _ = _capture_json(bind(ref["path"], ref["sha256"]))
        if (doc.get("schema") != "A2_HISTORICAL_EXPANDED_PRICE_INPUTS_V1"
                or doc.get("start") != report["data_date"] or doc.get("end") != report["data_date"]
                or not entry.get("vintage_semantics")
                or doc.get("vintage_semantics") != entry["vintage_semantics"]):
            raise ValueError("VINTAGE_EXPANDED_MANIFEST_SCHEMA_OR_CLOCK_CHANGED")
        rows = [row for row in doc.get("lineage", []) if row.get("ticker") == entry["ticker"]]
        wrapper_fields = {"source", "expanded_anchor_manifest", "calendar_lineage", "price_warnings"}
        if (len(rows) != 1 or rows[0] != {key:value for key,value in entry.items()
                                        if key not in wrapper_fields}):
            raise ValueError("VINTAGE_EXPANDED_LINEAGE_CHANGED:"+entry["ticker"])
        adapter = {"path": str(original.ADAPTER_PATH.resolve()), "sha256": original.ADAPTER_SHA}
        coverage = {"path": str(original.COVERAGE_PATH.resolve()), "sha256": original.COVERAGE_SHA}
        def normalized(ref):
            if not isinstance(ref,dict) or set(ref) != {"path","sha256"}:
                raise ValueError("VINTAGE_EXPANDED_REFERENCE_INVALID")
            return {"path":str(Path(ref["path"]).resolve()), "sha256":ref["sha256"]}
        verified_sources = [normalized(item) for item in doc.get("verified_sources", [])]
        if (normalized(doc.get("references", {}).get("coverage", {})) != coverage
                or adapter not in verified_sources or coverage not in verified_sources):
            raise ValueError("VINTAGE_EXPANDED_FIXED_AUTHORITY_CHANGED")
        for item in (adapter, coverage): bind(item["path"], item["sha256"])
        implementation = doc.get("implementation_refs", [])
        expected_implementations = {str(Path(original.__file__).resolve()),
            str((Path(original.__file__).resolve().parent/
                 "research/a2/inference/historical_top40_prices.py").resolve())}
        if (len(implementation) != 2
                or {str(Path(item["path"]).resolve()) for item in implementation} != expected_implementations):
            raise ValueError("VINTAGE_EXPANDED_IMPLEMENTATION_UNBOUND")
        for item in implementation: bind(item["path"], item["sha256"])
        return {"manifest": ref, "adapter": adapter, "coverage": coverage,
                "implementation_refs": implementation}
    proof = []
    current_raw = {row["ticker"] for row in new_report.get("ranked_rows", []) if row.get("rank",41) <= 40}
    accepted_candidates = accepted_candidates or {}
    if existing_candidate_tail and not set(tickers) <= current_raw | set(accepted_candidates):
        raise ValueError("VINTAGE_CURRENT_RAW_CANDIDATE_REQUIRED")
    for name in sorted(tickers):
        pairs = [[row for row in rows if row["ticker"] == name] for rows in (old_entries,new_entries)]
        if any(len(rows) != 1 for rows in pairs):
            raise ValueError("VINTAGE_TICKER_LINEAGE_UNAVAILABLE:"+name)
        a,b = pairs[0][0],pairs[1][0]
        fields = ("ticker","code","source","price_basis","anchor_date")
        if (any(not a.get(key) or a.get(key) != b.get(key) for key in fields)
                or a["price_basis"] != BASIS):
            raise ValueError("VINTAGE_ANCHOR_OR_ADAPTER_CHANGED:"+name)
        bindings = [adapter_binding(entry, report) for entry,report in
                    ((a,old_report),(b,new_report))]
        if (bool(bindings[0]) != bool(bindings[1]) or bindings[0] is not None and
                (bindings[0].get("schema") != bindings[1].get("schema")
                 or bindings[0]["implementation_refs"] != bindings[1]["implementation_refs"])):
            raise ValueError("VINTAGE_EXPANDED_IMPLEMENTATION_CHANGED:"+name)
        sid = identity(name,a["code"],old_members)
        if (sid != identity(name,b["code"],new_members)
                or name in accepted_candidates and sid != accepted_candidates[name]):
            raise ValueError("VINTAGE_SECURITY_IDENTITY_CHANGED:"+name)
        native = bindings[0] is not None and bindings[0].get("schema") == "NATIVE_MOOMOO_ANCHOR"
        if native and any(entry.get("security_id") != sid for entry in (a,b)):
            raise ValueError("VINTAGE_SECURITY_IDENTITY_CHANGED:"+name)
        anchors = [[ref for ref in entry["raw_sources"] if ref.get("role") == "ORIGINAL_ANCHOR"] for entry in (a,b)]
        if not native and (not anchors[0] or anchors[0] != anchors[1]):
            raise ValueError("VINTAGE_ORIGINAL_RAW_ANCHOR_CHANGED:"+name)
        indirect_old_refs = []
        for entry, scope in ((a,old["refs"]),(b,fresh["refs"])):
            for ref in entry["raw_sources"]:
                source = {key:ref[key] for key in ("path","sha256")}
                if source not in scope:
                    # An unused old CURRENT_RAW leaf may be owned transitively
                    # by the already hash-verified old report/input_lineage.
                    # The original anchor and every fresh leaf stay direct-bound.
                    if not (existing_candidate_tail and entry is a and
                            (ref.get("role") in {"CURRENT_RAW", "CURRENT_CATALOG_RAW"}
                             or native and ref.get("role") == "NATIVE_MOOMOO_ANCHOR")):
                        raise ValueError("VINTAGE_RAW_SOURCE_UNBOUND:"+name)
                    indirect_old_refs.append(source)
                bind(source["path"],source["sha256"])
        native_scopes = []
        if native:
            # Reuse the original normalized-to-provider-leaf native validator.
            # Retain only the unique original anchor bar, not two full histories.
            first = []
            for entry,report,scope in ((a,old_report,old["refs"]),(b,new_report,fresh["refs"])):
                source = entry["anchor_proof"].get("native_source",{})
                if not isinstance(source,dict) or not source.get("path") or not source.get("sha256") or not source.get("raw_inputs"):
                    raise ValueError("VINTAGE_NATIVE_SOURCE_UNBOUND:"+name)
                sources = [{key:source[key] for key in ("path","sha256")},*source["raw_inputs"]]
                if entry is b and any({key:item[key] for key in ("path","sha256")} not in scope for item in sources):
                    raise ValueError("VINTAGE_RAW_SOURCE_UNBOUND:"+name)
                native_scopes.append([native_readable(item,report) for item in sources])
                frame = reader._native_anchor(entry,bind)
                first.append(frame.loc[frame.trade_date.eq(pd.Timestamp(a["anchor_date"])),
                    ["trade_date",*original.PRICE_FIELDS]].reset_index(drop=True))
                del frame
            if any(len(frame) != 1 for frame in first):
                raise ValueError("VINTAGE_NATIVE_ANCHOR_ROW_UNBOUND:"+name)
            try: pd.testing.assert_frame_equal(first[0],first[1],check_exact=True,check_dtype=False)
            except AssertionError as exc: raise ValueError("VINTAGE_NATIVE_ANCHOR_VALUES_CHANGED:"+name) from exc
        if a["raw_sources"] == b["raw_sources"] and not existing_candidate_tail:
            raise ValueError("VINTAGE_SAME_RAW_PROOF_CHANGED_PRICE:"+name)
        x = before.loc[before.ticker.eq(name),"trade_date"]
        y = incoming.loc[incoming.ticker.eq(name)&incoming.trade_date.le(pd.Timestamp(prior_end)),"trade_date"]
        extra = y.loc[~y.isin(x)]
        if existing_candidate_tail:
            if (x.empty or not x.is_unique or not y.is_unique or not x.isin(y).all()
                    or extra.empty or extra.le(x.max()).any()):
                raise ValueError("VINTAGE_OLD_HISTORY_KEYS_CHANGED:"+name)
        elif set(x) != set(y) or len(x) != len(y):
            raise ValueError("VINTAGE_OLD_HISTORY_KEYS_CHANGED:"+name)
        try: pd.testing.assert_frame_equal(factors(a),factors(b),check_exact=True,check_dtype=False)
        except AssertionError as exc: raise ValueError("VINTAGE_PAST_REHAB_FACTS_CHANGED:"+name) from exc
        proof.append({"ticker":name,"code":a["code"],"security_id":sid,"anchor_date":a["anchor_date"],
            "original_anchor_refs":anchors[0],"accepted_raw_sources":a["raw_sources"],"incoming_raw_sources":b["raw_sources"],
            "accepted_rehab":a["rehab"],"incoming_rehab":b["rehab"],"past_factor_stream_exact":True,
            "origin_end":origin_end,"prior_consumed_end":outer_end,
            "rehab_facts_through":factor_end,
            "expanded_adapter_bindings":bindings if bindings[0] is not None and not native else None,
            **({"native_anchor_bindings":bindings,"native_first_raw_bar_exact":True,
                "native_physical_date_scopes":native_scopes,
                "old_frozen_equivalence_claimed":False} if native else {}),
            **({"existing_current_raw_candidate_tail":name in current_raw,
                "accepted_unconsumed_raw_candidate_tail":name in accepted_candidates,
                "accepted_ticker_last_date":str(x.max().date()),
                "appended_past_dates":[str(day.date()) for day in sorted(extra)],
                "transitively_bound_unused_old_raw_sources":indirect_old_refs}
               if existing_candidate_tail else {})})
    verify_refs(refs)
    return {"schema":"HGB_ACCEPTED_CLOSED_VINTAGE_CONTINUATION_V1",
        "policy":"ACCEPTED_OLD_KNOWN_FIELDS_ONLY_NEW_QUALIFIED_DATES",
        "accepted_report":old_ref,"incoming_report":new_ref,"through":prior_end,
        "ticker_proofs":proof,"source_refs":list({(ref["path"],ref["sha256"]):ref for ref in refs}.values()),
        "historical_price_revisions_applied":False,"model_feature_eligibility_granted":False}


def _advance_research_capture(paths, prior_ref, report_path, open_path, execution_end):
    """Keep accepted as-of marks; append only qualified new/mature fields."""
    from scripts.research.a2.evaluation.demo_performance import canonical_manifest, reviewed_events
    from scripts.research.a2.evaluation.demo_performance_prices import load_execution_prices, PRICE_COLUMNS
    from scripts.research.a2.portfolio import selected_hgb as selected
    package, prior, bound_ref, observation = bound_selected_research(paths, prior_ref)
    input_ref, old = prior_price_capture(prior)
    report, report_ref = _capture_json(report_path)
    signal = selected._date(report["data_date"])
    prior_end = prior["performance_period"]["end"]
    if (report.get("status") != "READY" or not "2026-01-01" <= signal < "2027-01-01"
            or signal < prior_end or (open_path is None) != (execution_end is None)
            or (open_path is not None and (signal != prior_end
                or report_ref != package["source_refs"]["current/report.json"]))):
        raise ValueError("PRIOR_PRICE_CONTINUATION_CLOCK_OR_REPORT_INVALID")
    end = execution_end or signal
    if end <= prior_end or not end < "2027-01-01":
        raise ValueError("PRIOR_PRICE_NEW_EXECUTION_REQUIRED")
    from scripts import daily_recommendation_inputs as calendar_inputs
    calendar = calendar_inputs.latest_completed_session(
        calendar_inputs.load_frozen_binding(paths.repo_root), datetime.now(timezone.utc))
    if signal not in calendar["sessions"] or signal > calendar["target_date"]:
        raise ValueError("PRIOR_PRICE_COMPLETED_SIGNAL_REQUIRED")
    # A replay may stop short of this already captured close because a bound
    # unconsumed candidate was omitted from that capture. Reusing it unchanged
    # cannot repair the recorded missing execution keys; use the original
    # qualified append path instead. This confers no input eligibility.
    blocked = prior.get("blocked_next") or {}
    blocked_keys = blocked.get("keys")
    recapture_missing_eligible = (package.get("policy_id",selected.LEGACY_POLICY) == selected.LEGACY_POLICY
        and prior.get("status") == "PARTIAL"
        and blocked.get("reason") == "ELIGIBLE_EXECUTION_PRICES_MISSING"
        and blocked.get("signal_date") == prior_end and blocked.get("execution_date") == signal
        and isinstance(blocked_keys,list) and bool(blocked_keys)
        and all(isinstance(key,list) and len(key)==2 and key[0] in {prior_end,signal}
                and isinstance(key[1],str) and bool(key[1]) for key in blocked_keys))
    if (open_path is None and not old.get("execution_open") and old.get("end_date") == signal
            and not recapture_missing_eligible):
        # A partial replay may already own a fully qualified later closed capture.
        # Rebind that exact accepted leaf as a derived input, without asking for
        # prices of a newer current package or changing any original capture.
        accepted = prior["source_refs"]
        parent = old.get("research_input_owner")
        if (old.get("gaps") != [] or old.get("event_review_resolved") is not True
                or report_ref not in old["refs"]
                or any(ref not in accepted for ref in (input_ref, old["captured_prices"], old["events"], *old["refs"]))
                or (parent is not None and (parent not in old["refs"] or parent not in accepted))):
            raise ValueError("PRIOR_PRICE_CLOSED_CAPTURE_BINDING_INVALID")
        refs = list({(ref["path"], ref["sha256"]): ref for ref in
            [*accepted, *old["refs"], input_ref, old["captured_prices"], old["events"], bound_ref, report_ref]}.values())
        prices = _capture_parquet(old["captured_prices"], columns=PRICE_COLUMNS,
            date_column="trade_date", start=old["start_date"], stop=pd.Timestamp(signal) + pd.Timedelta(days=1))
        prices["trade_date"] = pd.to_datetime(prices.trade_date)
        if (prices.empty or prices.trade_date.max() != pd.Timestamp(signal)
                or prices.duplicated(["ticker", "trade_date"]).any()
                or not np.isfinite(prices[["open", "close"]].to_numpy(float)).all()
                or not prices[["open", "close"]].gt(0).all().all()):
            raise ValueError("PRIOR_PRICE_CLOSED_CAPTURE_PRICES_INVALID")
        import pyarrow.parquet as pq
        columns = pq.read_schema(old["events"]["path"]).names
        event_date = "event_date" if "event_date" in columns else "trade_date"
        events = _capture_parquet(old["events"], date_column=event_date,
            start="1900-01-01", stop=pd.Timestamp(signal) + pd.Timedelta(days=1))
        resolved, _ = reviewed_events(events, old.get("event_review"), refs)
        if not resolved:
            raise ValueError("PRIOR_PRICE_CLOSED_CAPTURE_REVIEW_INVALID")
        verify_refs([input_ref, old["captured_prices"], old["events"], bound_ref, report_ref, observation])
        metadata = {**old, "refs": refs, "research_input_owner": bound_ref,
            "selected_package_observation": observation,
            "capture_reuse": {"prices_ref": old["captured_prices"], "inputs_ref": input_ref,
                "accepted_asof_open_source": None, "known_price_fields_all_exact": True,
                "matured_fields": [], "ignored_recorded_vintage_revisions":
                    {field: 0 for field in ("open", "close", "high", "low", "volume")},
                "new_qualified_raw_candidate_history": [], "model_feature_eligibility_granted": False,
                "reused_accepted_closed_capture": True}}
        return {"prices": prices, "events": events}, metadata
    current_raw_candidates = {row["ticker"] for row in report.get("ranked_rows", []) if row.get("rank", 41) <= 40}
    raw_candidates = set(current_raw_candidates)
    # The accepted prior also owns unexecuted intermediate candidate identities.
    # Read only missing dates from its original ranking vintage, using the same
    # strict Raw Top40 validator as the existing missing-feature owner.
    score_rows = [row for row in prior.get("shared_scores_historical", [])
                  if prior_end <= row["signal_date"] <= signal]
    raw_candidates.update(row["ticker"] for row in score_rows if row["raw_rank"] <= 40)
    known_dates = {row["signal_date"] for row in score_rows} | {signal}
    ranking_refs = list({(str(Path(ref["path"]).resolve()), ref["sha256"]): ref
        for ref in prior["source_refs"] if Path(ref["path"]).name == "rankings.parquet"}.values())
    ranking_frames, candidate_refs = [], []
    # Use the same immutable accepted snapshots that later supply score_panel.
    # The prior can stop before an archived signal that is no longer current.
    consumed = {item["signal_date"] for strategy in prior["strategies"].values()
                for item in strategy["targets"]}
    active_policy, active_path = selected.active_policy(paths)
    legacy_pending_scope = (active_policy == selected.LEGACY_POLICY
        and package.get("policy_id",selected.LEGACY_POLICY) == selected.LEGACY_POLICY)
    accepted, accepted_refs = (accepted_snapshots(package, Path(active_path).parent / "history", selected)
                               if legacy_pending_scope else ({},[]))
    pending_candidates, accepted_candidate_signals = {}, []
    def pending_identity(rows):
        for row in rows:
            if row["raw_rank"] > 40: continue
            # Keep the original name-only prior projection, but it grants no
            # new historical-tail exception without an already bound identity.
            if "security_id" not in row: continue
            ticker, sid = row["ticker"], row["security_id"]
            if not isinstance(sid,str) or not sid.strip() or ticker in pending_candidates and pending_candidates[ticker] != sid:
                raise ValueError("PRIOR_PRICE_UNCONSUMED_CANDIDATE_IDENTITY_CHANGED:" + ticker)
            pending_candidates[ticker] = sid
    if legacy_pending_scope: pending_identity(score_rows)
    for day, snapshot in accepted.items():
        if prior_end <= day <= signal and day not in consumed:
            known_dates.add(day)  # This accepted date must not join a later ranking vintage.
            rows = snapshot["report_binding"]["raw_top40"]
            pending_identity(rows)
            raw_candidates.update(row["ticker"] for row in rows)
            accepted_candidate_signals.append({"signal_date":day,
                "tickers":sorted(row["ticker"] for row in rows),
                "report":snapshot["source_refs"]["current/report.json"],
                "features":snapshot["source_refs"]["current/selected_hgb_features.parquet"]})
    if accepted_candidate_signals: candidate_refs.extend(accepted_refs)
    if ranking_refs:
        # A partial replay need not list unexecuted shared scores. The exact
        # original recorded prediction vintage still owns those date/Raw40
        # identities, just as it does in _load_prior_sources below.
        original_ref = {"path": str(selected.DEFAULT_SOURCE_ROOT / "test2026/predictions.parquet"),
                        "sha256": selected.REPLAY_HASHES["test2026/predictions.parquet"]}
        if original_ref not in prior["source_refs"]:
            raise ValueError("PRIOR_RESEARCH_ORIGINAL_PREDICTION_BINDING_REQUIRED")
        recorded = _capture_parquet(original_ref, columns=["signal_date", "ticker", "security_id", "raw_rank", "raw_score", "pred_hgb", "pred_q10"],
            date_column="signal_date", start=prior_end, stop=pd.Timestamp(signal) + pd.Timedelta(days=1))
        for day, group in recorded.groupby("signal_date"):
            day = str(pd.Timestamp(day).date())
            selected._score_rows(group, signal_date=day)  # Original full Raw40/security/score identity gate.
            if not np.isfinite(group.pred_q10.to_numpy(float)).all():
                raise ValueError("RECORDED_PREDICTIONS_NONFINITE:" + day)
            known_dates.add(day)
            raw_candidates.update(group.ticker)
        candidate_refs.append(original_ref)
    for ref in ranking_refs:
        frame = _capture_parquet(ref, columns=["target_date", "ticker", "security_id", "rank", "score", "model_sha256", "model_year"],
            date_column="target_date", start=prior_end, stop=pd.Timestamp(signal) + pd.Timedelta(days=1))
        frame = frame.loc[~pd.to_datetime(frame.target_date).dt.strftime("%Y-%m-%d").isin(known_dates)]
        if not frame.empty:
            ranking_frames.append(frame); candidate_refs.append(ref)
    if ranking_frames:
        from scripts.research.a2.evaluation.demo_performance import _validate_rankings, MODEL_2026_SHA
        ranked = _validate_rankings(pd.concat(ranking_frames, ignore_index=True).drop_duplicates(),
                                    {"2026": {"sha256": MODEL_2026_SHA}})
        raw_candidates.update(ranked.ticker)
    names = set(old.get("execution_open", {}).get("qualified_tickers", []))
    names.update(row["ticker"] for row in package["shared_scores"]["current"]["rows"])
    names.update(raw_candidates)
    for strategy in prior["strategies"].values():
        if strategy["targets"]:
            names.update(row["ticker"] for row in strategy["targets"][-1]["rows"] if row["target_weight"] > 0)
    historical, _ = canonical_manifest(Path(paths.daily_root)/"A2_historical_top40/latest.json")
    if reference(historical) not in old["refs"]:
        raise ValueError("PRIOR_PRICE_HISTORICAL_AUTHORITY_CHANGED")
    # Candidate scores and price inputs must retain the same security even if
    # this is the ticker's first appearance in the accepted price capture.
    pending_identity_bindings = []
    if pending_candidates:
        from scripts.research.a2.evaluation.demo_performance_prices import _current_entries
        def pending_ref(path, sha):
            ref = {"path":str(Path(path).resolve()),"sha256":sha}
            verify_refs([ref]);candidate_refs.append(ref);return Path(ref["path"])
        entries, _ = _current_entries(report_path, Path(historical).resolve(),
                                     reference(historical)["sha256"], pending_ref)
        universe = report["universe"]
        mapped_ref = {"path":str((Path(universe["report_path"]).parent / "mapped_members.parquet").resolve()),
                      "sha256":universe["universe_members_sha256"]}
        members = _capture_parquet(mapped_ref,columns=["ticker","moomoo_symbol","security_id"])
        candidate_refs.append(mapped_ref)
        if members.ticker.duplicated().any():
            raise ValueError("PRIOR_PRICE_PENDING_CURRENT_IDENTITY_DUPLICATE")
        members = members.set_index("ticker")
        historical_rows = None
        for name,sid in pending_candidates.items():
            current_rows = [row for row in entries if row["ticker"] == name]
            if len(current_rows) > 1:
                raise ValueError("PRIOR_PRICE_PENDING_CURRENT_LINEAGE_DUPLICATE:" + name)
            if name in members.index:
                member = members.loc[name]
                if (not isinstance(member.security_id,str) or member.security_id != sid
                        or not isinstance(member.moomoo_symbol,str) or not member.moomoo_symbol):
                    raise ValueError("PRIOR_PRICE_PENDING_SECURITY_IDENTITY_CHANGED:" + name)
                code = member.moomoo_symbol
            else:
                code = None
            if not current_rows or code is None:
                if historical_rows is None:
                    document,_ = _capture_json(historical)
                    historical_input = document["price_manifest"]
                    document,_ = _capture_json(historical_input["path"],historical_input["sha256"])
                    candidate_refs.append(historical_input);historical_rows = document["lineage"]
                matches = [row for row in historical_rows if row.get("ticker") == name
                           and row.get("cusips") == [sid] and (code is None or row.get("code") == code)]
                if len(matches) != 1 or not matches[0].get("code"):
                    raise ValueError("PRIOR_PRICE_PENDING_HISTORICAL_IDENTITY_UNBOUND:" + name)
                code = matches[0]["code"]
            if current_rows and current_rows[0]["code"] != code:
                raise ValueError("PRIOR_PRICE_PENDING_TRANSPORT_CODE_CHANGED:" + name)
            pending_identity_bindings.append({"ticker":name,"security_id":sid,"code":code})
    fresh = load_execution_prices(paths, historical, tickers=sorted(names),
        current_report_path=report_path, start=old["start_date"], end=signal,
        **({"execution_open_manifest":open_path,"execution_end":execution_end}
           if open_path is not None else {}))
    if fresh.get("price_basis") != BASIS or fresh.get("gaps"):
        raise ValueError("PRIOR_PRICE_DELTA_UNQUALIFIED:"+json.dumps(fresh.get("gaps", [])))
    if fresh.get("event_review") != old.get("event_review"):
        raise ValueError("PRIOR_PRICE_EVENT_REVIEW_IDENTITY_CHANGED")
    stop = pd.Timestamp(prior_end)+pd.Timedelta(days=1)
    old_prices = _capture_parquet(old["captured_prices"], columns=PRICE_COLUMNS,
        date_column="trade_date", start=old["start_date"], stop=stop)
    old_prices["trade_date"] = pd.to_datetime(old_prices.trade_date)
    incoming = fresh["prices"].copy(); incoming["trade_date"] = pd.to_datetime(incoming.trade_date)
    if incoming.duplicated(["ticker","trade_date"]).any() or incoming.trade_date.gt(pd.Timestamp(end)).any():
        raise ValueError("PRIOR_PRICE_DELTA_DATE_KEYS_INVALID")
    if open_path is not None:
        phase = fresh.get("execution_open",{})
        terminal = incoming.loc[incoming.trade_date.eq(pd.Timestamp(execution_end))]
        if (phase.get("manifest") != reference(open_path)
                or phase.get("signal_end_date") != signal or phase.get("execution_end_date") != execution_end
                or set(phase.get("qualified_tickers",[])) != names
                or set(terminal.ticker) != names or len(terminal) != len(names)
                or not terminal[["close","high","low","volume"]].isna().all().all()
                or not np.isfinite(terminal.open).all() or not terminal.open.gt(0).all()):
            raise ValueError("PRIOR_PRICE_NEW_OPEN_PHASE_INVALID")
    maturity_keys, identity_refs = _prior_open_maturity(old,old_prices,prior_end,fresh,report,historical)
    result = old_prices.set_index(["ticker","trade_date"])
    newer = incoming.set_index(["ticker","trade_date"])
    overlap = newer.index.intersection(result.index)
    for field in ("open","close","high","low","volume"):
        known_keys = overlap[result.loc[overlap,field].notna()]
        values = newer.loc[known_keys,field].to_numpy(float)
        if (not np.isfinite(values).all() or (values < 0).any()
                or (field != "volume" and (values <= 0).any())):
            raise ValueError("PRIOR_PRICE_INCOMING_VINTAGE_VALUE_INVALID:"+field)
    revisions = {field:0 for field in ("open","close","high","low","volume")}
    changed_keys, closed_tickers, vintage_rows = {}, set(), []
    for field in revisions:
        changed = result.loc[overlap,field].notna() & result.loc[overlap,field].ne(newer.loc[overlap,field])
        keys = list(overlap[changed]); changed_keys[field] = keys
        revisions[field] = len(keys)
        closed_tickers.update(key[0] for key in keys if field != "open" or key not in maturity_keys)
    vintage_proof = None
    if closed_tickers:
        field = next(field for field,keys in changed_keys.items()
                     if any(field != "open" or key not in maturity_keys for key in keys))
        if (selected.active_policy(paths)[0] != selected.LEGACY_POLICY
                or package.get("policy_id",selected.LEGACY_POLICY) != selected.LEGACY_POLICY):
            raise ValueError("PRIOR_PRICE_ACCEPTED_CLOSED_FIELD_CHANGED:"+field+":VINTAGE_LEGACY_POLICY_REQUIRED")
        try:
            vintage_proof = _accepted_closed_vintage_proof(old,fresh,report_path,historical,prior_end,
                                                          old_prices,
                # This proof owns only previously captured keys. The complete
                # incoming frame still must pass the original new-key gates below.
                incoming.loc[newer.index.isin(result.index)],closed_tickers,
                _field_keys=[(key[0],key[1],field) for field,keys in changed_keys.items()
                             for key in keys if field != "open" or key not in maturity_keys],
                _capture_ref=input_ref)
        except (ValueError,KeyError,TypeError,OSError,AssertionError) as exc:
            raise ValueError("PRIOR_PRICE_ACCEPTED_CLOSED_FIELD_CHANGED:VINTAGE_PROOF:"+str(exc)) from exc
        for field,keys in changed_keys.items():
            for key in keys:
                if field == "open" and key in maturity_keys: continue
                value = newer.at[key,field]
                if not np.isfinite(value) or value < 0 or (field != "volume" and value <= 0):
                    raise ValueError("PRIOR_PRICE_INCOMING_VINTAGE_VALUE_INVALID:"+field)
                vintage_rows.append({"ticker":key[0],"trade_date":str(key[1].date()),"field":field,
                    "accepted_value":float(result.at[key,field]),"incoming_value":float(value)})
        vintage_proof["field_differences"] = vintage_rows
    missing_fields = []
    for field in ("close","high","low","volume"):
        unknown = result[field].isna()
        for key in result.index[unknown]:
            if key not in maturity_keys or key not in newer.index:
                raise ValueError("PRIOR_PRICE_MATURE_CLOSE_MISSING:"+str(key))
            value = newer.at[key,field]
            if not np.isfinite(value) or value < 0 or (field != "volume" and value <= 0):
                raise ValueError("PRIOR_PRICE_MATURE_FIELD_INVALID:"+field)
            result.at[key,field] = value
            missing_fields.append({"ticker":key[0],"trade_date":str(key[1].date()),"field":field})
    # Both qualified vintages retain the original known fields. Only the
    # original open-only terminal may mature previously unavailable fields.
    additions = newer.loc[~newer.index.isin(result.index)]
    new_candidates = raw_candidates-set(old_prices.ticker)
    existing_past = [(ticker,day) for ticker,day in additions.index
                     if day <= pd.Timestamp(prior_end) and ticker not in new_candidates]
    candidate_tail_proof = None
    if existing_past:
        last_dates = old_prices.groupby("ticker").trade_date.max()
        if (selected.active_policy(paths)[0] != selected.LEGACY_POLICY
                or package.get("policy_id",selected.LEGACY_POLICY) != selected.LEGACY_POLICY
                or any(ticker not in current_raw_candidates | set(pending_candidates) or ticker not in last_dates
                       or day <= last_dates[ticker] for ticker,day in existing_past)):
            raise ValueError("PRIOR_PRICE_UNBOUND_OLD_DATE_ADDITION")
        values = additions.loc[existing_past,["open","close","high","low","volume"]]
        if (not np.isfinite(values.to_numpy(float)).all()
                or not values[["open","close","high","low"]].gt(0).all().all()
                or not values.volume.ge(0).all()):
            raise ValueError("PRIOR_PRICE_CANDIDATE_TAIL_VALUES_INVALID")
        try:
            candidate_tail_proof = _accepted_closed_vintage_proof(old,fresh,report_path,historical,
                prior_end,old_prices,incoming,{ticker for ticker,day in existing_past},
                existing_candidate_tail=True, accepted_candidates=pending_candidates)
        except (ValueError,KeyError,TypeError,OSError,AssertionError) as exc:
            raise ValueError("PRIOR_PRICE_UNBOUND_OLD_DATE_ADDITION:"+str(exc)) from exc
    added_history = sorted({ticker for ticker,day in additions.index if day <= pd.Timestamp(prior_end)})
    prices = pd.concat([result, additions]).reset_index()[PRICE_COLUMNS]
    before = old_prices.set_index(["ticker","trade_date"])
    after = prices.set_index(["ticker","trade_date"])
    for field in ("open","close","high","low","volume"):
        known = before[field].notna()
        pd.testing.assert_series_equal(before.loc[known,field], after.loc[before.index[known],field], check_exact=True)
    events = _capture_parquet(old["events"])
    columns = sorted(set(events.columns)|set(fresh["events"].columns))
    known_event_keys = set(zip(events.ticker, pd.to_datetime(events.event_date), events.audit_kind))
    # Duplicate old audit keys must retain their detected facts too; keeping
    # the old row must not hide a conflicting incoming raw jump or identity.
    event_keys = ["ticker", "event_date", "audit_kind"]
    before_events = events.assign(event_date=pd.to_datetime(events.event_date)).set_index(event_keys)
    after_events = fresh["events"].assign(event_date=pd.to_datetime(fresh["events"].event_date)).set_index(event_keys)
    overlap_events = before_events.index.intersection(after_events.index)
    if vintage_proof is not None or candidate_tail_proof is not None:
        # Old observed event facts cannot disappear under the incoming vintage.
        scope = old_prices.ticker.isin(incoming.ticker)
        names_with_history = set(old_prices.loc[scope,"ticker"])
        prior_events = before_events.loc[before_events.index.get_level_values("ticker").isin(names_with_history)]
        prior_events = prior_events.loc[prior_events.index.get_level_values("event_date") <= pd.Timestamp(prior_end)]
        if (not prior_events.index.isin(after_events.index).all()
                or (len(prior_events) and not (set(before_events.columns)-{"resolution_status"}) <= set(after_events.columns))):
            raise ValueError("PRIOR_PRICE_PAST_EVENT_FACT_MISSING")
    fact_fields = sorted((set(before_events.columns) & set(after_events.columns)) - {"resolution_status"})
    if len(overlap_events):
        try:
            pd.testing.assert_frame_equal(before_events.loc[overlap_events, fact_fields].reset_index(drop=True),
                after_events.loc[overlap_events, fact_fields].reset_index(drop=True), check_dtype=False, check_exact=True)
        except AssertionError as exc:
            raise ValueError("PRIOR_PRICE_PAST_EVENT_FACT_CHANGED") from exc
    new_events = fresh["events"].loc[[key not in known_event_keys for key in zip(
        fresh["events"].ticker,pd.to_datetime(fresh["events"].event_date),fresh["events"].audit_kind)]]
    past_events = new_events.loc[pd.to_datetime(new_events.event_date).le(pd.Timestamp(prior_end))]
    admitted_past_events = []
    if not past_events.empty:
        # New qualified Raw candidate history can carry its original detected
        # jump audit. It remains unreviewed; no consumed holding is restated.
        event_names = set(past_events.ticker)
        consumed_positive = {row["ticker"] for strategy in prior["strategies"].values()
            for target in strategy["targets"] if target["signal_date"] <= prior_end
            for row in target["rows"] if row["target_weight"] > 0}
        bound_codes = {row["ticker"]:row["code"] for row in pending_identity_bindings}
        fields = {"code", "raw_jump", "source_event_date", "aligned_to_next_session",
                  "factor_a", "factor_b", "share_event", "manual_wolf"}
        raw_past = past_events.loc[past_events.audit_kind.eq("LARGE_RAW_MOVE_NO_VENDOR_EVENT")]
        vendor_past = past_events.loc[past_events.audit_kind.eq("APPLIED_CORPORATE_ACTION")]
        # The original reader has already applied and source-qualified these
        # price-only vendor events. A newly captured, never-consumed candidate
        # must retain that audit too; it does not restate any accepted holding.
        # Unknown jumps keep their original review gate. Share/manual events
        # and every old price/event/positive target remain protected.
        if (not legacy_pending_scope or not event_names <= new_candidates
                or not event_names <= current_raw_candidates | set(pending_candidates)
                or event_names & (set(events.ticker) | consumed_positive)
                or not fields <= set(past_events.columns)
                or not past_events.audit_kind.isin(
                    ["LARGE_RAW_MOVE_NO_VENDOR_EVENT","APPLIED_CORPORATE_ACTION"]).all()
                or past_events.duplicated(event_keys).any()
                or any((row.ticker,pd.Timestamp(row.event_date)) not in additions.index
                       for row in past_events.itertuples(index=False))
                or not past_events.code.map(lambda value:isinstance(value,str) and bool(value)).all()
                or any(row.ticker in bound_codes and row.code != bound_codes[row.ticker]
                       for row in past_events.itertuples(index=False))
                or not past_events[["share_event","manual_wolf"]].eq(False).all().all()
                or (not raw_past.empty and (
                    not np.isfinite(raw_past.raw_jump.to_numpy(float)).all()
                    or not raw_past.raw_jump.abs().ge(.80).all()
                    or not raw_past[["source_event_date","factor_a","factor_b"]].isna().all().all()
                    or not raw_past.aligned_to_next_session.eq(False).all()))
                or (not vendor_past.empty and (
                    not vendor_past.raw_jump.isna().all()
                    or not np.isfinite(vendor_past[["factor_a","factor_b"]].to_numpy(float)).all()
                    or not vendor_past.factor_a.gt(0).all()
                    or vendor_past.source_event_date.isna().any()
                    or any(row.ticker not in bound_codes or row.code != bound_codes[row.ticker]
                           for row in vendor_past.itertuples(index=False))
                    or any(pd.Timestamp(row.source_event_date) > pd.Timestamp(row.event_date)
                           or row.aligned_to_next_session !=
                              (pd.Timestamp(row.source_event_date) != pd.Timestamp(row.event_date))
                           for row in vendor_past.itertuples(index=False))))):
            raise ValueError("PRIOR_PRICE_PAST_EVENT_REVISION")
        admitted_past_events = [{"ticker":row.ticker,"event_date":str(pd.Timestamp(row.event_date).date()),
            "audit_kind":row.audit_kind,"code":row.code,"resolution_status":"UNREVIEWED"}
            for row in past_events.itertuples(index=False)]
    events = pd.concat([events.reindex(columns=columns),new_events.reindex(columns=columns)],ignore_index=True)
    refs = [*old["refs"],*fresh["refs"],*identity_refs,*candidate_refs,input_ref,old["captured_prices"],old["events"],bound_ref,report_ref]
    if vintage_proof is not None: refs.extend(vintage_proof["source_refs"])
    if candidate_tail_proof is not None: refs.extend(candidate_tail_proof["source_refs"])
    verify_refs([*refs,observation])
    # The original review covers the full accepted audit, while fresh prices may
    # cover only today's candidates and held names. Keep every prior event row
    # and apply the unchanged full-review exact-fact gate to the bound union.
    resolved, _ = reviewed_events(events, fresh.get("event_review"), refs)
    if not resolved:
        raise ValueError("PRIOR_PRICE_NEW_EVENTS_UNREVIEWED")
    metadata = {**old, **{k:v for k,v in fresh.items() if k not in {"prices","events","refs"}},
        "refs":refs,"start_date":old["start_date"],"end_date":signal,"event_review_resolved":True,
        "research_input_owner":bound_ref,"selected_package_observation":observation,
        "capture_reuse":{"prices_ref":old["captured_prices"],"inputs_ref":input_ref,
            "accepted_asof_open_source":old.get("execution_open",{}).get("manifest"),
            "known_price_fields_all_exact":True,"matured_fields":missing_fields,
            "ignored_recorded_vintage_revisions":revisions,"new_qualified_raw_candidate_history":added_history,
            **({"new_qualified_raw_candidate_event_history":admitted_past_events} if admitted_past_events else {}),
            **({"accepted_closed_vintage_continuation":vintage_proof} if vintage_proof is not None else {}),
            **({"qualified_existing_raw_candidate_tails":candidate_tail_proof} if candidate_tail_proof is not None else {}),
            "accepted_unconsumed_raw_candidate_signals":accepted_candidate_signals,
            "accepted_unconsumed_price_identity_bindings":pending_identity_bindings,
            **({"recaptured_blocked_eligible_execution_prices":blocked} if recapture_missing_eligible else {}),
            "model_feature_eligibility_granted":False}}
    if open_path is None: metadata.pop("execution_open",None)
    return {"prices":prices.sort_values(["trade_date","ticker"]).reset_index(drop=True),"events":events},metadata



def _verify_prior_price_prefix(prices, inputs, prior, prices_ref):
    """Explicit replay calls must preserve the original consumed price fields."""
    old_ref, old = prior_price_capture(prior)
    reuse = inputs.get("capture_reuse", {})
    if (reuse.get("inputs_ref") != old_ref or reuse.get("prices_ref") != old["captured_prices"]
            or inputs.get("captured_prices") != prices_ref or reuse.get("known_price_fields_all_exact") is not True
            or old_ref not in inputs["refs"] or old["captured_prices"] not in inputs["refs"]):
        raise ValueError("PRIOR_RESEARCH_CAPTURE_LINEAGE_CHANGED")
    # Match the original replay reader's consumed start and the accepted old end.
    before = _capture_parquet(old["captured_prices"],date_column="trade_date",
        start="2025-11-01",stop=pd.Timestamp(prior["performance_period"]["end"])+pd.Timedelta(days=1))
    before["trade_date"] = pd.to_datetime(before.trade_date)
    before = before.set_index(["ticker","trade_date"])
    after = prices.set_index(["ticker","trade_date"])
    if not before.index.is_unique or not before.index.isin(after.index).all():
        raise ValueError("PRIOR_RESEARCH_CAPTURE_PRICE_KEYS_CHANGED")
    for field in ("open","close","high","low","volume"):
        known = before[field].notna()
        try:
            pd.testing.assert_series_equal(before.loc[known,field],
                after.loc[before.index[known],field],check_exact=True)
        except AssertionError as exc:
            raise ValueError("PRIOR_RESEARCH_CAPTURE_PRICE_PREFIX_CHANGED:"+field) from exc

def _reuse_execution_open_capture(paths, reuse, report_path, open_manifest_path, execution_end):
    """Extend one hash-bound open capture using only the original qualifier."""
    from scripts.research.a2.evaluation.demo_performance import canonical_manifest
    from scripts.research.a2.evaluation.demo_performance_prices import load_execution_prices, PRICE_COLUMNS
    if (set(reuse) != {"prices_ref", "inputs_ref"} or report_path is None
            or open_manifest_path is None or execution_end is None):
        raise ValueError("CAPTURE_REUSE_EXPLICIT_BINDINGS_REQUIRED")
    verify_refs(list(reuse.values()))
    old, _ = _capture_json(reuse["inputs_ref"]["path"], reuse["inputs_ref"]["sha256"])
    price_ref = reuse["prices_ref"]
    old_phase = old.get("execution_open", {})
    if old.get("captured_prices") != price_ref or not old_phase or not old.get("events"):
        raise ValueError("CAPTURE_REUSE_ORIGINAL_CAPTURE_BINDING_INVALID")
    new_ref = reference(open_manifest_path)
    new, _ = _capture_json(new_ref["path"], new_ref["sha256"])
    parent_ref = old_phase.get("manifest", {})
    if new.get("parent_execution_open_manifest") != parent_ref:
        raise ValueError("CAPTURE_REUSE_PARENT_MANIFEST_MISMATCH")
    parent, _ = _capture_json(parent_ref["path"], parent_ref["sha256"])
    report_ref = reference(report_path)
    signal = old.get("end_date")
    if (new.get("schema") != "A2_EXECUTION_OPEN_INPUTS_V1"
            or new.get("current_report") != parent.get("current_report")
            or new.get("current_report") != report_ref
            or report_ref not in old.get("refs", [])
            or new.get("signal_end_date") != signal
            or old_phase.get("signal_end_date") != signal
            or parent.get("signal_end_date") != signal
            or any(value != execution_end for value in (
                parent.get("execution_end_date"), new.get("execution_end_date"),
                old_phase.get("execution_end_date")))):
        raise ValueError("CAPTURE_REUSE_SIGNAL_REPORT_OR_CLOCK_CHANGED")
    if pd.Timestamp(new["as_of_utc"]) < pd.Timestamp(parent["as_of_utc"]):
        raise ValueError("CAPTURE_REUSE_AS_OF_CLOCK_REVERSED")
    for key in ("identity_binding", "historical_identity_binding"):
        if new.get(key) != parent.get(key):
            raise ValueError("CAPTURE_REUSE_IDENTITY_AUTHORITY_CHANGED")
    def records(document):
        rows = document.get("records", [])
        mapped = {row["ticker"]: row for row in rows}
        if len(mapped) != len(rows) or not rows:
            raise ValueError("CAPTURE_REUSE_DUPLICATE_OR_EMPTY_IDENTITY")
        return mapped
    prior_records, new_records = records(parent), records(new)
    if any(new_records.get(name) != row for name, row in prior_records.items()):
        raise ValueError("CAPTURE_REUSE_EXISTING_SECURITY_IDENTITY_CHANGED")
    if set(old_phase.get("qualified_tickers", [])) != set(prior_records):
        raise ValueError("CAPTURE_REUSE_ORIGINAL_OPEN_QUALIFICATION_INCOMPLETE")
    names = sorted(set(new_records) - set(prior_records))
    if not names:
        raise ValueError("CAPTURE_REUSE_NO_NEW_EXECUTION_NAMES")
    # A derived union must preserve every original real provider response row.
    lineage_refs = [parent_ref, new_ref, report_ref]
    for key in ("acquisition_manifest", "rehab_receipt"):
        before_ref, after_ref = parent[key], new[key]
        before, _ = _capture_json(before_ref["path"], before_ref["sha256"])
        after, _ = _capture_json(after_ref["path"], after_ref["sha256"])
        def provider_rows(document):
            rows = document.get("results", [])
            mapped = {row.get("code") or row.get("current_kline_provenance", {}).get("code")
                      or row.get("item", {}).get("moomoo_symbol"): row for row in rows}
            if None in mapped or len(mapped) != len(rows):
                raise ValueError("CAPTURE_REUSE_PROVIDER_UNION_IDENTITY_INVALID")
            return mapped
        a, b = provider_rows(before), provider_rows(after)
        if any(b.get(code) != row for code, row in a.items()):
            raise ValueError("CAPTURE_REUSE_ORIGINAL_PROVIDER_RECEIPT_CHANGED")
        lineage_refs.extend([before_ref, after_ref])
    refs = [*old.get("refs", []), *reuse.values(), old["events"], *lineage_refs]
    # Verify each actual source once; repeated identical refs confer no authority.
    def unique_refs(items):
        result = {}
        for ref in items:
            key = str(Path(ref["path"]).resolve())
            if key in result and result[key]["sha256"] != ref["sha256"]:
                raise ValueError("CONFLICTING_SOURCE_HASH:" + key)
            result[key] = ref
        return list(result.values())
    refs = unique_refs(refs)
    verify_refs(refs)
    historical, _ = canonical_manifest(Path(paths.daily_root) / "A2_historical_top40/latest.json")
    if reference(historical) not in old.get("refs", []):
        raise ValueError("CAPTURE_REUSE_HISTORICAL_AUTHORITY_CHANGED")
    delta = load_execution_prices(paths, historical, tickers=names,
        current_report_path=report_path, start=old["start_date"], end=signal,
        execution_open_manifest=open_manifest_path, execution_end=execution_end)
    if (delta.get("gaps") or set(delta.get("execution_open", {}).get("qualified_tickers", [])) != set(names)):
        raise ValueError("CAPTURE_REUSE_DELTA_OPEN_NOT_QUALIFIED:" + json.dumps(delta.get("gaps", [])))
    stop = pd.Timestamp(execution_end) + pd.Timedelta(days=1)
    dates = _capture_parquet(price_ref, columns=["trade_date"])
    if not pd.to_datetime(dates.trade_date).between(pd.Timestamp(old["start_date"]), pd.Timestamp(execution_end)).all():
        raise ValueError("CAPTURE_REUSE_ORIGINAL_PRICE_DATES_OUTSIDE_BOUNDARY")
    prices = _capture_parquet(price_ref, columns=PRICE_COLUMNS,
        date_column="trade_date", start=old["start_date"], stop=stop)
    def ordered(frame):
        return frame.sort_values(["trade_date", "ticker"]).reset_index(drop=True)
    previous = prices.loc[prices.ticker.isin(names)]
    completed = delta["prices"].loc[delta["prices"].trade_date.le(pd.Timestamp(signal))]
    try:
        pd.testing.assert_frame_equal(ordered(previous), ordered(completed),
                                      check_exact=True, check_dtype=False)
    except AssertionError as exc:
        raise ValueError("CAPTURE_REUSE_DELTA_HISTORY_PREFIX_CHANGED") from exc
    terminal = delta["prices"].loc[delta["prices"].trade_date.eq(pd.Timestamp(execution_end))]
    if (len(terminal) != len(names) or set(terminal.ticker) != set(names)
            or terminal.duplicated(["ticker", "trade_date"]).any()
            or not np.isfinite(terminal.open.to_numpy(float)).all() or not terminal.open.gt(0).all()
            or not terminal[["high", "low", "close", "volume"]].isna().all().all()):
        raise ValueError("CAPTURE_REUSE_TERMINAL_OPEN_ONLY_REQUIRED")
    events = _capture_parquet(old["events"])
    columns = sorted(set(events.columns) | set(delta["events"].columns))
    def event_order(frame):
        return frame.reindex(columns=columns).sort_values(
            ["event_date", "ticker", "audit_kind"]).reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(event_order(events.loc[events.ticker.isin(names)]),
            event_order(delta["events"]), check_exact=True, check_dtype=False)
    except AssertionError as exc:
        raise ValueError("CAPTURE_REUSE_DELTA_EVENT_AUDIT_CHANGED") from exc
    phase = {**old_phase, "manifest": new_ref, "as_of_utc": new["as_of_utc"],
        "qualified_tickers": sorted(new_records),
        "qualifications": [*old_phase["qualifications"], *delta["execution_open"]["qualifications"]]}
    refs = unique_refs([*refs, *delta["refs"]])
    verify_refs(refs)
    metadata = {**old, "refs": refs, "execution_open": phase,
        "capture_reuse": {"prices_ref": price_ref, "inputs_ref": reuse["inputs_ref"],
            "parent_execution_open_manifest": parent_ref, "delta_tickers": names,
            "existing_prices_all_fields_exact": True, "existing_event_audit_exact": True,
            "model_feature_eligibility_granted": False}}
    return {"prices": ordered(pd.concat([prices, terminal], ignore_index=True)), "events": events}, metadata


def _load_held_reuse(paths, sources, tickers, target):
    """Read real immutable receipts without a provider fallback or qualification."""
    from scripts.storage.storage_r2a import DataStore
    from scripts import daily_recommendation_prices as original
    publication_mode = set(sources) == {"publication", "rehab"}
    if not publication_mode and set(sources) != {"acquisition", "massive", "rehab"}:
        raise ValueError("HELD_REUSE_RECEIPT_SET_INCOMPLETE")
    guard = DataStore(paths)
    for ref in sources.values():
        guard._check_data_path(Path(ref["path"]))
    refs = list(sources.values())
    verify_refs(refs)
    if publication_mode:
        cached = json.loads(Path(sources["publication"]["path"]).read_text(encoding="utf-8"))
        # This is an existing publication, not a COMPLETE acquisition envelope.
        # The unchanged raw/overlap/calendar/rehab/event gates still qualify rows.
        if cached.get("provider") != "MASSIVE_GROUPED" or not isinstance(cached.get("catalog_records"), list):
            raise ValueError("HELD_PUBLICATION_CONTRACT_INVALID")
        inputs = cached.get("inputs_manifest", {})
        if not inputs.get("path") or not inputs.get("sha256"):
            raise ValueError("HELD_PUBLICATION_INPUT_BINDING_MISSING")
        guard._check_data_path(Path(inputs["path"]))
        verify_refs([inputs]); refs.append(inputs)
        acquired = {"results": [], "source": "EXISTING_LOCAL_PUBLICATION_NO_ACQUISITION"}
    else:
        acquired = json.loads(Path(sources["acquisition"]["path"]).read_text(encoding="utf-8"))
        cached = json.loads(Path(sources["massive"]["path"]).read_text(encoding="utf-8"))
    rehab_source = Path(sources["rehab"]["path"])
    rehab = json.loads(rehab_source.read_text(encoding="utf-8"))
    if ((not publication_mode and (cached.get("summary", {}).get("status") != "COMPLETE"
            or cached.get("contract", {}).get("provider") != "MASSIVE_GROUPED"))
            or rehab.get("source") != "MOOMOO_OPEND_GET_REHAB"
            or rehab.get("target_date") != target):
        raise ValueError("HELD_REUSE_SOURCE_CONTRACT_INVALID")
    selected = [row for row in cached["catalog_records"] if row["ticker"] in tickers]
    if len({row["ticker"] for row in selected}) != len(selected):
        raise ValueError("HELD_REUSE_DUPLICATE_PRICE_RECORD")
    records = {row["ticker"]: row for row in selected}
    if publication_mode:
        for row in selected:
            binding = row.get("lineage", {}).get("inputs_manifest", {})
            if (any(row.get(key) != value for key, value in {"dataset": "prices_daily_massive", "source": "MASSIVE_GROUPED", "adjustment": "raw", "format": "parquet"}.items())
                    or binding.get("path") != inputs["path"] or binding.get("sha256") != inputs["sha256"]):
                raise ValueError("HELD_PUBLICATION_RECORD_BINDING_INVALID")
            guard._check_data_path(Path(row["path"]))
            verify_refs([{"path": row["path"], "sha256": row["source_sha256"]}])
    if any(row.get("max_date") != target for row in selected):
        raise ValueError("HELD_REUSE_TARGET_PRICE_MISSING")
    for ticker in tickers:
        native = [row for row in acquired.get("results", [])
                  if row.get("item", {}).get("ticker") == ticker
                  and row.get("item", {}).get("adjustment") == "raw"
                  and row.get("item", {}).get("planned_end_date") == target
                  and row.get("status") in original.SUCCESS]
        if ticker not in records and len(native) != 1:
            raise ValueError("HELD_REUSE_TICKER_UNAVAILABLE:" + ticker)
    return acquired, records, rehab, rehab_source, refs


def supplement_held_prices(prices_path, inputs_path, output_dir, tickers, *, target="2026-09-29", repo_root="D:/us-tech-quant", reuse_sources=None):
    """Acquire real native tails and qualify against the accepted raw anchor.

    The original raw qualifier, exact-overlap merge, rehab adapter and event
    review remain authoritative. No catalog promotion or canonical data change.
    """
    sys.path.insert(0, str(Path(repo_root)))
    from scripts.common.storage_paths import resolve
    from scripts.research.a2.evaluation.demo_performance import canonical_manifest, reviewed_events
    from scripts.research.a2.evaluation import demo_performance_prices as reader
    from scripts.research.a2.inference.historical_top40_prices import _append_raw, _rehab_frame
    from scripts.research.a2.inference.historical_top40 import load_sessions
    from scripts.storage import refresh_market_data as acquisition
    from scripts import daily_recommendation_prices as original
    paths = resolve(Path(repo_root))
    historical, _ = canonical_manifest(Path(paths.daily_root) / "A2_historical_top40/latest.json")
    hist = json.loads(historical.read_text(encoding="utf-8"))
    proof = hist["price_manifest"]
    verify_refs([proof])
    accepted = json.loads(Path(proof["path"]).read_text(encoding="utf-8"))["lineage"]
    entries = {entry["ticker"]: entry for entry in accepted if entry["ticker"] in tickers}
    if set(entries) != set(tickers):
        raise ValueError("HELD_NATIVE_ANCHOR_NOT_QUALIFIED")
    sessions, _ = load_sessions(paths)
    calendar = pd.DatetimeIndex(pd.to_datetime(sessions))
    first = min(pd.Timestamp(entry["raw_end"]) for entry in entries.values())
    start = str(calendar[calendar <= first][-6].date())
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    members = [{"ticker": ticker, "moomoo_symbol": entries[ticker]["code"]} for ticker in tickers]
    if any(row["moomoo_symbol"] != "US." + row["ticker"] for row in members):
        raise ValueError("EXPLICIT_HELD_NATIVE_MAPPING_REQUIRED")
    args = SimpleNamespace(work_root=output / "acquisition", repo_root=Path(repo_root), tickers=list(tickers),
        universe_csv=None, start=start, end=target, adjustments=["raw"], host=None, port=None,
        max_retries=1, execute=True)
    reused_refs = []
    rehab_source = output / "rehab/rehab_receipt.json"
    massive_records = {}
    if reuse_sources is not None:
        # The original source, raw, rehab, PIT-prefix and event gates below
        # still qualify every reused receipt. Transport is never reopened.
        acquired, massive_records, rehab, rehab_source, reused_refs = _load_held_reuse(
            paths, reuse_sources, tickers, target)
    else:
        acquired = acquisition.run(args)
    if reuse_sources is None and acquired["status"] not in {"ACQUIRED", "ALL_INTERVALS_REUSED"}:
        from scripts.storage import refresh_massive_market as massive
        from scripts.storage.refresh_current_massive import load_api_key, _cached_days
        key = load_api_key(paths)
        if not key:
            raise ValueError("HELD_NATIVE_QUOTA_AND_ALTERNATE_CREDENTIAL_UNAVAILABLE")
        cached = _cached_days([paths.cache_root / "data_acquisition/massive_20260913",
                              paths.cache_root / "daily_recommendation/massive_current"], target)
        days = [str(day.date()) for day in calendar if pd.Timestamp(start) <= day <= pd.Timestamp(target)]
        work = output / "massive/checkpoints"
        for day in days:
            if day in cached:
                source, saved = cached[day]
                destination = work / "days" / day / "checkpoint.json"
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read_bytes())
        summary = massive.acquire(days, tickers, key, work, output_root=output / "massive/normalized")
        if summary["status"] != "COMPLETE":
            raise ValueError("HELD_ALTERNATE_ACQUISITION_INCOMPLETE")
        records = json.loads(Path(summary["manifest_path"]).read_text(encoding="utf-8"))["catalog_records"]
        massive_records = {record["ticker"]: record for record in records}
    if reuse_sources is None:
        rehab = original.refresh_rehab(paths, members, output / "rehab", target)
    metadata = json.loads(Path(inputs_path).read_text(encoding="utf-8"))
    refs = list(metadata["refs"]) + reused_refs + [reference(prices_path), reference(inputs_path), proof, reference(historical)]
    captured = {}
    def verify(path, sha):
        ref = {"path": str(Path(path).resolve()), "sha256": sha}
        verify_refs([ref])
        captured[ref["path"]] = ref
        return Path(path)
    coverage = json.loads(original.verify(original.COVERAGE_PATH, original.COVERAGE_SHA).read_text(encoding="utf-8"))
    wolf = {"event_date": coverage["adjustment"]["wolf_event_date"],
            "quantity_multiplier": coverage["adjustment"]["wolf_new_shares_per_old_share"]}
    adapter = original._adapter(target)
    captured_end = max(pd.Timestamp(target), pd.Timestamp(metadata.get("end_date", target)))
    bounded_stop = min(captured_end + pd.Timedelta(days=1), pd.Timestamp("2027-01-01"))
    prices = _capture_parquet(reference(prices_path), date_column="trade_date",
        start="2025-11-01", stop=bounded_stop)
    prices["trade_date"] = pd.to_datetime(prices.trade_date)
    events = pd.read_parquet(original.verify(metadata["events"]["path"], metadata["events"]["sha256"]))
    contracts = []
    from scripts.storage.storage_r2a import DataStore
    store = DataStore(paths)
    for ticker in tickers:
        entry = entries[ticker]
        raw = reader._raw(entry, verify, store, {})
        receipts = [row for row in acquired["results"] if row["item"]["ticker"] == ticker
                    and row.get("status") in original.SUCCESS]
        bridge = None
        if ticker in massive_records:
            from scripts.storage.storage_r2a import DataStore
            record = massive_records[ticker]
            recent, bridge = original._qualified_massive_tail(record, raw, ticker, target, DataStore(paths))
            verify(record["path"], record["source_sha256"])
            for leaf in bridge["raw_inputs"]:
                verify(leaf["path"], leaf["sha256"])
                verify(leaf["checkpoint_path"], leaf["checkpoint_sha256"])
            receipt = {"provider": "MASSIVE_GROUPED", "qualification": bridge}
        else:
            if len(receipts) != 1:
                raise ValueError("HELD_NATIVE_RECEIPT_INCOMPLETE:" + ticker)
            receipt = receipts[0]
            path = verify(receipt["path"], receipt["sha256"])
            native = pd.read_csv(path)
            acquisition.validate_records(native.to_dict("records"), receipt["item"])
            recent = original._raw_frame(native, entry["code"])
        raw = _append_raw(raw, recent, calendar)
        if raw.trade_date.max() != pd.Timestamp(target):
            raise ValueError("HELD_NATIVE_TARGET_DATE_MISSING:" + ticker)
        fresh = [row for row in rehab["results"] if row.get("code") == entry["code"] and row.get("status") == "PASS"]
        if len(fresh) != 1:
            raise ValueError("HELD_REHAB_MISSING:" + ticker)
        factor = fresh[0]
        if pd.Timestamp(factor["fetched_at"]) < pd.Timestamp(target).tz_localize("America/New_York") + pd.Timedelta(hours=16):
            raise ValueError("HELD_REHAB_PREDATES_TARGET_CLOSE")
        factors = _rehab_frame(factor["path"], factor["sha256"], entry["code"], factor["row_count"], verify)
        adjusted, detected = adapter.adjusted_price_frame(entry["code"], ticker, raw, factors, wolf)
        old = prices.loc[prices.ticker.eq(ticker)]
        overlap = old.merge(adjusted, on=["trade_date", "ticker"], suffixes=("_old", "_new"))
        if len(overlap) != len(old) or any(not overlap[field + "_old"].eq(overlap[field + "_new"]).all()
                                            for field in ("open", "close", "high", "low", "volume")):
            raise ValueError("HELD_PIT_PREFIX_CHANGED:" + ticker)
        tail = adjusted.loc[adjusted.trade_date.gt(old.trade_date.max()), prices.columns]
        prices = pd.concat([prices, tail], ignore_index=True)
        if detected:
            fresh_events = pd.DataFrame(detected)
            fresh_events["ticker"] = ticker
            events = pd.concat([events, fresh_events], ignore_index=True).drop_duplicates(["ticker", "event_date", "audit_kind"])
        contracts.append({"ticker": ticker, "accepted_anchor": entry, "acquisition_receipt": receipt,
            "fresh_rehab": factor, "qualification": "ORIGINAL_NATIVE_ANCHOR_EXACT_RAW_OVERLAP_ALL_SESSIONS_UNCHANGED_PIT_PREFIX"})
    refs.extend(captured.values())
    refs.extend([reference(rehab_source),
                 {"path": str(original.ADAPTER_PATH), "sha256": original.ADAPTER_SHA},
                 {"path": str(original.COVERAGE_PATH), "sha256": original.COVERAGE_SHA}])
    verify_refs(refs)
    reviewed_events(events, metadata.get("event_review"), refs)
    price_output, event_output = output / "prices.parquet", output / "events.parquet"
    prices.sort_values(["ticker", "trade_date"]).to_parquet(price_output, index=False)
    events.to_parquet(event_output, index=False)
    metadata.update(refs=refs, events=reference(event_output), captured_prices=reference(price_output), held_tail_contracts=contracts)
    input_output = output / "price_inputs.json"
    input_output.write_text(json.dumps(metadata, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
    return price_output, input_output


def common_clock(sessions, signal_dates, target, execution_end=None):
    """Require each prior session signal; report first gap and retain a prefix."""
    calendar = pd.DatetimeIndex(pd.to_datetime(sessions)).normalize().sort_values().unique()
    present = set(pd.DatetimeIndex(pd.to_datetime(signal_dates)).normalize())
    pairs, gap = [], None
    for signal, execution in zip(calendar[:-1], calendar[1:]):
        if signal < pd.Timestamp("2026-01-02") or signal > pd.Timestamp(target) or execution > pd.Timestamp(execution_end or target):
            continue
        if signal not in present:
            gap = {"signal_date": str(signal.date()), "execution_date": str(execution.date()),
                   "reason": "COMPLETE_FROZEN_SIGNAL_FEATURES_MISSING"}
            break
        pairs.append((signal, execution))
    if not pairs:
        raise ValueError("NO_CONTIGUOUS_EXECUTION_WINDOW")
    return pairs, gap


def event_clock(pairs, audit):
    if "audit_kind" not in audit:
        return pairs, None
    unresolved = audit.loc[audit.audit_kind.eq("LARGE_RAW_MOVE_NO_VENDOR_EVENT")
        & audit.resolution_status.eq("UNREVIEWED")]
    dates = pd.to_datetime(unresolved.event_date)
    active = unresolved.loc[dates.ge(pairs[0][0]) & dates.le(pairs[-1][1])]
    if active.empty:
        return pairs, None
    first = pd.to_datetime(active.event_date).min()
    rows = active.loc[pd.to_datetime(active.event_date).eq(first)]
    gap = {"execution_date": str(first.date()), "reason": "UNRESOLVED_CANDIDATE_CORPORATE_ACTION",
           "tickers": sorted(set(rows.ticker.astype(str)))}
    retained = [(signal, execution) for signal, execution in pairs if execution < first]
    if not retained:
        raise ValueError("NO_EVENT_QUALIFIED_EXECUTION_WINDOW:" + str(gap))
    return retained, gap


def score_panel(frames, selected, runtime):
    """Project only model inputs and call predict, never any fitting API."""
    days = {}
    for frame in frames:
        column = next((c for c in ("signal_date", "trade_date", "target_date") if c in frame), None)
        if column is None:
            raise ValueError("FEATURE_DATE_MISSING")
        frame = frame.rename(columns={column: "signal_date"})
        for _, group in frame.groupby("signal_date"):
            if {"pred_hgb", "pred_q10"}.issubset(group):
                # The immutable original panel includes valid pre-recorded
                # predictions for a few short-return-history members. Reuse
                # those qualified scores; never impute missing lag inputs.
                day = str(pd.Timestamp(group.signal_date.iloc[0]).date())
                if len(group) != 40 or group.ticker.nunique() != 40 or set(group.raw_rank) != set(range(1, 41)):
                    raise ValueError("RECORDED_TOP40_INCOMPLETE:" + day)
                if not np.isfinite(group[["raw_rank", "raw_score", "pred_hgb", "pred_q10"]].to_numpy(float)).all():
                    raise ValueError("RECORDED_PREDICTIONS_NONFINITE:" + day)
                identity = ["signal_date", "ticker", "raw_rank", "raw_score"]
                if "security_id" in group:
                    identity.append("security_id")
                normal = group[[*identity, *selected.FEATURES, "pred_hgb", "pred_q10"]].copy()
            else:
                normal, day = selected._normalise_day(group, runtime)
                normal["pred_hgb"] = runtime["model"].predict(normal[list(selected.FEATURES)])
                normal["pred_q10"] = runtime["q10"].predict(normal[list(selected.FEATURES)])
            if day in days:
                old = days[day].sort_values("ticker").reset_index(drop=True)
                new = normal.sort_values("ticker").reset_index(drop=True)
                pd.testing.assert_frame_equal(old, new, check_exact=True, check_dtype=False)
            else:
                days[day] = normal
    panel = pd.concat(days.values(), ignore_index=True).sort_values(["signal_date", "raw_rank"])
    return panel


def _capture_json(path, expected=None):
    path = Path(path).resolve()
    data = path.read_bytes()
    ref = {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}
    if expected is not None and ref["sha256"] != expected:
        raise ValueError("SOURCE_HASH_MISMATCH:" + str(path))
    return json.loads(data.decode("utf-8-sig")), ref


def _capture_parquet(ref, *, columns=None, date_column=None, start=None, stop=None, price_keys=None):
    if date_column is None:
        data = Path(ref["path"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != ref["sha256"]:
            raise ValueError("SOURCE_HASH_MISMATCH:" + ref["path"])
        return pd.read_parquet(BytesIO(data), columns=columns)
    # Map one qualified file handle; avoid a full serialized-byte copy and
    # apply Arrow's column/date predicate before materializing any row values.
    import pyarrow as pa
    import pyarrow.dataset as ds
    with pa.memory_map(ref["path"], "r") as mapped:
        def validate_bytes():
            mapped.seek(0)
            digest = hashlib.sha256()
            for block in iter(lambda: mapped.read(1024 * 1024), b""):
                digest.update(block)
            if digest.hexdigest() != ref["sha256"]:
                raise ValueError("SOURCE_HASH_MISMATCH:" + ref["path"])
            mapped.seek(0)
        validate_bytes()
        fragment = ds.ParquetFileFormat().make_fragment(mapped)
        kind = fragment.physical_schema.field(date_column).type
        def boundary(value):
            moment = pd.Timestamp(value)
            if pa.types.is_string(kind) or pa.types.is_large_string(kind):
                return pa.scalar(moment.strftime("%Y-%m-%d"), type=kind)
            if pa.types.is_date(kind):
                return pa.scalar(moment.date(), type=kind)
            return pa.scalar(moment.to_pydatetime(), type=kind)
        predicate = ((ds.field(date_column) >= boundary(start))
                     & (ds.field(date_column) < boundary(stop)))
        if price_keys is not None:
            predicate = predicate & ds.field("ticker").isin(sorted({key[0] for key in price_keys}))
            predicate = predicate & ds.field(date_column).isin([boundary(key[1]).as_py() for key in price_keys])
        result = fragment.to_table(columns=columns, filter=predicate).to_pandas()
        validate_bytes()
    return result


def accepted_snapshots(package, history_root, selected):
    """Read only versions selected by the existing package/repair receipt contract."""
    folder = Path(history_root).resolve()
    current = package.get("shared_scores", {}).get("current", {})
    cutoff = current.get("requested_signal_date") or current.get("signal_date")
    snapshots, refs = {}, []
    for key in sorted(package.get("source_refs", {})):
        match = re.fullmatch(r"history/(\d{4}-\d{2}-\d{2})\.json", key)
        if match is None:
            continue
        day = selected._date(match.group(1))
        if not cutoff or day > selected._date(cutoff):
            raise ValueError("ACCEPTED_SNAPSHOT_AFTER_PACKAGE_SIGNAL:" + day)
        path, sha, receipt = selected._revision_selection(package, folder, day)
        snapshot = selected._validate_snapshot(_capture_json(path, sha)[0])
        if snapshot["signal_date"] != day:
            raise ValueError("ACCEPTED_SNAPSHOT_DATE_MISMATCH:" + day)
        snapshots[day] = snapshot
        refs.append({"path": str(path), "sha256": sha})
        if receipt is not None:
            refs.append(dict(receipt))
        refs.extend(ref for name, ref in snapshot["source_refs"].items()
                    if name not in snapshot["observation_only_source_refs"])
    return snapshots, refs


def _accepted_feature_frame(snapshot, selected):
    """Reuse frozen normalization, then bind actual feature identity to the archive."""
    ref = snapshot["source_refs"]["current/selected_hgb_features.parquet"]
    verify_refs([ref])
    normal, day = selected._normalise_day(_capture_parquet(ref), {"pd": pd, "np": np})
    expected = pd.DataFrame(snapshot["report_binding"]["raw_top40"])
    if day != snapshot["signal_date"]:
        raise ValueError("ACCEPTED_FEATURE_DATE_OR_IDENTITY_MISMATCH")
    normal = _bind_feature_identity(normal, expected)
    verify_refs([ref])
    return normal


def _bind_feature_identity(normal, expected):
    """Reuse an already bound same-day Top40; never repair present identities."""
    columns = ["ticker", "security_id", "raw_rank", "raw_score"]
    if "security_id" not in normal:
        # Legacy saved features omit this column. Attach only identities owned
        # by the accepted archive/report or this exact accepted research prior.
        normal = normal.merge(expected[["ticker", "security_id"]], on="ticker", how="left", validate="one_to_one")
    pd.testing.assert_frame_equal(normal[columns].sort_values("ticker").reset_index(drop=True),
        expected[columns].sort_values("ticker").reset_index(drop=True), check_exact=True, check_dtype=False)
    return normal


def verify_accepted_scores(panel, snapshots, selected):
    for day, snapshot in snapshots.items():
        group = panel.loc[pd.to_datetime(panel.signal_date).dt.strftime("%Y-%m-%d").eq(day)]
        actual = selected._score_rows(group, signal_date=day)
        expected = [{**row, "signal_date": day} for row in snapshot["shared_scores"]["rows"]]
        if json.dumps(sorted(actual, key=lambda row: row["ticker"]), sort_keys=True, allow_nan=False) != json.dumps(
                sorted(expected, key=lambda row: row["ticker"]), sort_keys=True, allow_nan=False):
            raise ValueError("ACCEPTED_SHARED_SCORE_MISMATCH:" + day)


def _accepted_owner(owner_path, selected, target_date=None):
    owner, owner_ref = _capture_json(owner_path)
    snapshots, refs = accepted_snapshots(owner, owner_path.parent / "history", selected)
    current = owner.get("shared_scores", {}).get("current", {})
    if current.get("status") == "READY":
        day = selected._date(current["signal_date"])
        if target_date is None or day <= target_date:
            previous = snapshots.get(day)
            same_refs = previous is not None and all(owner.get("source_refs", {}).get(name) == previous["source_refs"].get(name)
                for name in ("current/report.json", "current/selected_hgb_features.parquet"))
            captured = selected._capture_snapshot(owner, owner_ref["sha256"],
                previous["report_binding"] if same_refs else None)
            if day in snapshots and not selected._same_snapshot_decision(captured, snapshots[day]):
                raise ValueError("ACCEPTED_CURRENT_SNAPSHOT_CONFLICT:" + day)
            snapshots[day] = captured
    verify_refs([owner_ref])
    return owner_ref, snapshots, refs


def _load_sources(paths, selected, root, feature_paths=(), *, target_date=None):
    refs = []
    original = root / "test2026/predictions.parquet"
    original_ref = {"path": str(original), "sha256": selected.REPLAY_HASHES["test2026/predictions.parquet"]}
    verify_refs([original_ref])
    refs.append(original_ref)
    prediction_columns = ["signal_date", "ticker", "security_id", "raw_rank", "raw_score",
                          *selected.FEATURES, "pred_hgb", "pred_q10"]
    stop = min(pd.Timestamp(target_date) + pd.Timedelta(days=1), pd.Timestamp("2027-01-01")) if target_date else pd.Timestamp("2027-01-01")
    frames = [_capture_parquet(original_ref, columns=prediction_columns,
        date_column="signal_date", start="2026-01-01", stop=stop)]
    owner_path = Path(paths.daily_root) / "A2_selected_hgb/latest.json"
    snapshots, owner_ref = {}, None
    if owner_path.is_file():
        owner_ref, snapshots, archive_refs = _accepted_owner(owner_path, selected, target_date)
        refs.extend(archive_refs)
        for day, snapshot in snapshots.items():
            if target_date is None or day <= target_date:
                frames.append(_accepted_feature_frame(snapshot, selected))
                refs.extend(ref for name, ref in snapshot["source_refs"].items()
                            if name not in snapshot["observation_only_source_refs"])
        verify_refs([owner_ref])
    for report_path in sorted((Path(paths.daily_root) / "A2_today_recommendation/runs").glob("*/report.json")):
        immutable = report_path.with_name("recommendation_source.json")
        if immutable.is_file():
            candidate = json.loads(immutable.read_text(encoding="utf-8"))
            if candidate.get("status") == "READY" and candidate.get("selected_hgb_features"):
                report_path = immutable
        report = json.loads(report_path.read_text(encoding="utf-8"))
        day = report.get("data_date")
        if day in snapshots or (target_date is not None and day and day > target_date):
            continue  # The accepted package owns this date; directory order does not select inputs.
        if report.get("status") != "READY" or not report.get("selected_hgb_features"):
            continue
        binding = report["selected_hgb_features"]
        if not isinstance(binding, dict) or not binding.get("path") or not binding.get("sha256"):
            continue
        captured = {}
        day, _, _ = selected._current_day(paths, report_path, captured)
        if day is not None:
            frames.append(day)
            refs.extend(captured.values())
    for path in feature_paths:
        refs.append(reference(path))
        frames.append(pd.read_parquet(path))
    return frames, refs, owner_ref, snapshots


def _load_prior_sources(paths, selected, root, prior, target):
    """Old accepted feature bytes plus exactly the canonical unexecuted signals."""
    used = {item["signal_date"] for strategy in prior["strategies"].values() for item in strategy["targets"]}
    if not used:
        raise ValueError("PRIOR_RESEARCH_EXECUTED_SIGNALS_REQUIRED")
    last = max(used)
    if not "2026-01-01" <= last <= target < "2027-01-01":
        raise ValueError("PRIOR_RESEARCH_FEATURE_WINDOW_INVALID")
    stop = pd.Timestamp(last)+pd.Timedelta(days=1)
    original = root/"test2026/predictions.parquet"
    original_ref = {"path":str(original),"sha256":selected.REPLAY_HASHES["test2026/predictions.parquet"]}
    if original_ref not in prior["source_refs"]:
        raise ValueError("PRIOR_RESEARCH_ORIGINAL_PREDICTION_BINDING_REQUIRED")
    # Reuse unexecuted recorded predictions from this exact original vintage.
    # Daily feature snapshots below retain the consumed cutoff; canonical
    # accepted snapshots continue to own their newer unexecuted input vintages.
    original_stop = pd.Timestamp(target)+pd.Timedelta(days=1)
    columns = ["signal_date","ticker","security_id","raw_rank","raw_score",
               *selected.FEATURES,"pred_hgb","pred_q10"]
    frames = [_capture_parquet(original_ref,columns=columns,date_column="signal_date",
                              start="2026-01-01",stop=original_stop)]
    refs = [original_ref]
    seen = set()
    for ref in prior["source_refs"]:
        if Path(ref["path"]).name != "selected_hgb_features.parquet":
            continue
        key = (str(Path(ref["path"]).resolve()),ref["sha256"])
        if key in seen: continue
        seen.add(key)
        frame = _capture_parquet(ref,date_column="trade_date",start="2026-01-01",stop=stop)
        if not frame.empty:
            if "security_id" not in frame:
                bound = []
                for day, group in frame.groupby("trade_date",sort=False):
                    day = str(pd.Timestamp(day).date())
                    expected = pd.DataFrame([row for row in prior["shared_scores_historical"]
                                             if row["signal_date"] == day])
                    selected._score_rows(expected,signal_date=day)  # Original complete40/SID/finite score gate.
                    bound.append(_bind_feature_identity(group,expected))
                frame = pd.concat(bound,ignore_index=True)
            frames.append(frame);refs.append(ref)
    owner_path = Path(selected.active_policy(paths)[1])
    observation, snapshots, archive_refs = _accepted_owner(owner_path, selected, target)
    fresh = {day:value for day,value in snapshots.items() if last < day <= target}
    for day,snapshot in fresh.items():
        frames.append(_accepted_feature_frame(snapshot,selected))
        refs.extend(ref for name,ref in snapshot["source_refs"].items()
                    if name not in snapshot["observation_only_source_refs"])
    refs.extend(archive_refs)
    verify_refs([observation])
    return frames,refs,observation,fresh


def _verify_prior_scores(panel, prior, selected):
    used = {item["signal_date"] for strategy in prior["strategies"].values() for item in strategy["targets"]}
    for day in used:
        rows = selected._score_rows(panel.loc[pd.to_datetime(panel.signal_date).eq(pd.Timestamp(day))],signal_date=day)
        expected = [row for row in prior["shared_scores_historical"] if row["signal_date"]==day]
        order = lambda values: sorted(values,key=lambda row:row["ticker"])
        if not expected or order(rows)!=order(expected):
            raise ValueError("PRIOR_RESEARCH_SHARED_SCORE_CHANGED:"+day)


def load_sources(paths, selected, root, feature_paths=(), *, target_date=None):
    # Existing two-value callers retain their interface and immutable refs only.
    frames, refs, _, _ = _load_sources(paths, selected, root, feature_paths, target_date=target_date)
    return frames, refs


def recover_missing_features(paths, frames, prices, sessions, selected, *, prior_research=None):
    """Use recorded Top40 and the original, hash-bound feature function only."""
    if prior_research is None:
        pointer = Path(paths.daily_root) / "A2_updated_research/latest.json"
        captured_bytes = pointer.read_bytes()
        old = json.loads(captured_bytes)
        canonical = Path(old["report_path"])
        if canonical.read_bytes() != captured_bytes:
            raise ValueError("PERFORMANCE_POINTER_CANONICAL_MISMATCH")
        rank_ref = old["outputs"]["rankings"]
        verify_refs([rank_ref])
        ranked = pd.read_parquet(rank_ref["path"])
        ranking_refs = [rank_ref, reference(canonical)]
    else:
        known_dates = {pd.Timestamp(day).normalize() for frame in frames for day in
            frame[next(c for c in ("signal_date","trade_date","target_date") if c in frame)].unique()}
        ranking_refs = list({(str(Path(ref["path"]).resolve()),ref["sha256"]):ref
            for ref in prior_research["source_refs"] if Path(ref["path"]).name=="rankings.parquet"}.values())
        columns = ["target_date","ticker","security_id","rank","score"]
        stop = prices.trade_date.max()+pd.Timedelta(days=1)
        captures = [_capture_parquet(ref,columns=columns,date_column="target_date",start="2026-01-01",stop=stop)
                    for ref in ranking_refs]
        ranked = pd.concat(captures,ignore_index=True).drop_duplicates() if captures else pd.DataFrame(columns=columns)
        ranked = ranked.loc[~pd.to_datetime(ranked.target_date).isin(known_dates)]
        if ranked.duplicated(["target_date","ticker"]).any():
            raise ValueError("PRIOR_RESEARCH_RANKING_VINTAGE_CONFLICT")
    known = {pd.Timestamp(day).normalize() for frame in frames for day in
             frame[next(c for c in ("signal_date", "trade_date", "target_date") if c in frame)].unique()}
    missing = sorted(day for day in set(pd.to_datetime(ranked.target_date)) - known
                     if day >= pd.Timestamp("2026-01-02") and day <= prices.trade_date.max())
    if not missing:
        return [], []
    source = Path(paths.repo_root) / "scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py"
    ref = {"path": str(source), "sha256": "fd4fe78d27bfbf57c89343d60550366ccf7fcbf3d6a65e7ef66f28405d050c19"}
    verify_refs([ref])
    module = selected._load_module("_independent_original_features", source)
    features = module.build_stock_state_features(prices[["ticker", "trade_date", "close", "volume"]])
    calendar = pd.DatetimeIndex(pd.to_datetime(sessions)).normalize().sort_values().unique()
    recovered = []
    for day in missing:
        top = ranked.loc[pd.to_datetime(ranked.target_date).eq(day)].copy()
        if len(top) != 40:
            continue
        top = top.rename(columns={"target_date": "signal_date", "rank": "raw_rank", "score": "raw_score"})
        base = features.loc[pd.to_datetime(features.trade_date).eq(day), ["ticker", *selected.BASE_FEATURES]]
        snapshot = top[["signal_date", "ticker", "security_id", "raw_rank", "raw_score"]].merge(base, on="ticker", how="left", validate="one_to_one")
        slots = calendar[calendar <= day][-11:]
        if len(slots) != 11 or slots[-1] != day:
            continue
        for index in range(10):
            snapshot[f"lag_ret_{index:02d}"] = np.nan
        for ticker in snapshot.ticker:
            group = prices.loc[prices.ticker.eq(ticker)].set_index("trade_date").close.reindex(slots)
            returns = group.pct_change(fill_method=None)
            for index in range(10):
                snapshot.loc[snapshot.ticker.eq(ticker), f"lag_ret_{index:02d}"] = returns.iloc[-1-index]
        if np.isfinite(snapshot[[*selected.BASE_FEATURES, *(f"lag_ret_{i:02d}" for i in range(10))]].to_numpy(float)).all():
            recovered.append(snapshot)
    return recovered, [*ranking_refs, ref]


def replay_common(replay, name, spec, panel, prices, runtime, pairs):
    """Same frozen target callback, with the validated official session clock.

    E5's original dates_for derives sessions from QQQ prices. QQQ is only a
    calendar proxy, not a strategy holding; this producer uses the verified
    official calendar directly and requires every signal in that calendar.
    """
    days = {pd.Timestamp(day): group for day, group in panel.groupby("signal_date")}
    price_keys = set(zip(pd.to_datetime(prices.trade_date), prices.ticker))
    execution_by_signal = dict(pairs)
    decisions = []
    def target(signal, shares, values, nav):
        exceptional = [(str(execution_by_signal[signal].date()), ticker) for ticker, qty in shares.items()
            if qty > 0 and (execution_by_signal[signal], ticker) in runtime.get("unresolved_events", set())]
        if exceptional:
            raise HeldEventUnresolved(signal, execution_by_signal[signal], exceptional)
        missing = [(str(day.date()), ticker) for day in (signal, execution_by_signal[signal])
                   for ticker, qty in shares.items() if qty > 0 and (day, ticker) not in price_keys]
        if missing:
            raise HeldPriceMissing(signal, execution_by_signal[signal], missing)
        group = days[signal]
        if spec is None:
            wanted = {str(ticker): .05 for ticker in group.loc[group.raw_rank.le(20), "ticker"]}
            diagnostic = {"raw_targets": wanted.copy(), "solver_failed": False}
        else:
            policy = runtime.get("policy")
            if policy is None:
                wanted, diagnostic = runtime["optimizer"].solve(group, shares, values, nav,
                    runtime["risk"], spec, signal)
            else:
                from scripts.research.a2.portfolio import selected_hgb
                wanted, diagnostic = selected_hgb.solve_targets(group, shares, values, nav,
                    runtime["risk"], spec, signal, optimizer=runtime["optimizer"], policy=policy)
        for ticker in sorted(set(shares) | set(wanted) | set(diagnostic["raw_targets"])):
            decisions.append({"candidate": name, "signal_date": signal, "ticker": ticker,
                "signal_close_shares": shares.get(ticker, 0.), "signal_close_weight": values.get(ticker, 0.) / nav,
                "raw_target_weight": diagnostic["raw_targets"].get(ticker, 0.),
                "target_weight": wanted.get(ticker, 0.), "solver_failed": diagnostic["solver_failed"]})
        return wanted
    result = replay(name, target, prices, [execution for _, execution in pairs],
                    {execution: signal for signal, execution in pairs})
    return result, pd.DataFrame(decisions)


def qualify_execution_pairs(panel, prices, pairs, policy):
    """Original complete eligible-close/next-open gate, independent of holdings."""
    from scripts.research.a2.portfolio import selected_hgb as selected
    if policy not in {selected.LEGACY_POLICY, selected.DIRECT_POLICY}:
        raise ValueError("UNSUPPORTED_HGB_POLICY")
    gap = None
    # Require genuine prices for all eligible names at close and next open.
    indexed = prices.set_index(["trade_date", "ticker"])
    qualified = []
    for signal, execution in pairs:
        group = panel.loc[panel.signal_date.eq(signal)]
        names = set(group.loc[group.raw_rank.le(20), "ticker"])
        if policy == selected.DIRECT_POLICY:
            names.update(group.sort_values(["pred_hgb", "ticker"], ascending=[False, True]).head(20).ticker)
        missing = [(str(day.date()), name) for day in (signal, execution) for name in names
                   if (day, name) not in indexed.index]
        if missing:
            gap = {"signal_date": str(signal.date()), "execution_date": str(execution.date()),
                   "reason": "ELIGIBLE_EXECUTION_PRICES_MISSING", "keys": missing}
            break
        qualified.append((signal, execution))
    return qualified, gap


def load_frozen_close_clock_replay(root):
    """Load the existing frozen E5 close-clock owner, without model decoding.

    Each call to the returned replay starts with its original empty shares and
    unit cash. Source checks grant no market-data or evaluation authority.
    """
    from scripts.research.a2.portfolio import selected_hgb as selected
    root = Path(root)
    close_path = root / "audit_20260926/close_clock.py"
    verify_refs([{"path": str(close_path),
                  "sha256": selected.FROZEN_HASHES["audit_20260926/close_clock.py"]}])
    # Read only the hash-qualified supervised close-clock function. The
    # legacy module imports unrelated RL training dependencies (torch).
    # No RL function or training entry point is imported or executed.
    tree = ast.parse(close_path.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "close_clock_replay")
    e5_path = Path("D:/us-tech-quant-results/A2_EXECUTION_EFFICIENCY_R2_PREREGISTERED_HYSTERESIS/run_a2_execution_efficiency_r2.py")
    e5_ref = {"path": str(e5_path), "sha256": E5_SOURCE_SHA}
    verify_refs([e5_ref])
    namespace = {"inspect": inspect, "rl_policy": SimpleNamespace(E5=e5_path)}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(close_path), "exec"), namespace)
    e5 = selected._load_module("_independent_pit_e5", e5_path)
    if e5.COST_RATE != .001:
        raise ValueError("FROZEN_ONE_WAY_COST_CHANGED")
    replay = namespace["close_clock_replay"](e5)
    return replay, e5_ref


def run_extension(prices_path, price_inputs_path, output_dir, *, repo_root="D:/us-tech-quant",
                  feature_paths=(), target_date=None, sessions=None, policy=None, include_legacy=False,
                  execution_open_manifest=None, execution_end=None, prior_research_manifest=None):
    sys.path.insert(0, str(Path(repo_root)))
    from scripts.common.storage_paths import resolve
    from scripts.research.a2.portfolio import selected_hgb as selected
    from scripts.research.a2.inference.historical_top40 import load_sessions
    paths = resolve(Path(repo_root))
    root = selected.DEFAULT_SOURCE_ROOT
    selected.verify_frozen(root)
    runtime = selected._runtime(root)
    policy = policy or selected.LEGACY_POLICY
    if target_date is not None and not "2026-01-01" <= selected._date(target_date) < "2027-01-01":
        raise ValueError("DESCRIPTIVE_2026_TEST_BOUNDARY_REQUIRED")
    if policy not in {selected.LEGACY_POLICY, selected.DIRECT_POLICY}:
        raise ValueError("UNSUPPORTED_HGB_POLICY")
    runtime = {**runtime, "policy": policy}
    inputs = json.loads(Path(price_inputs_path).read_text(encoding="utf-8"))
    if inputs.get("price_basis") != BASIS:
        raise ValueError("QUALIFIED_PIT_PRICE_BASIS_REQUIRED")
    producer_path = Path(__file__).resolve()
    producer_bytes = producer_path.read_bytes()
    producer_observation = {"path": str(producer_path), "sha256": hashlib.sha256(producer_bytes).hexdigest()}
    prior = None
    if prior_research_manifest is not None:
        if inputs.get("research_input_owner") != prior_research_manifest:
            raise ValueError("PRIOR_RESEARCH_CAPTURE_BINDING_REQUIRED")
        package, prior, prior_ref, _ = bound_selected_research(paths,prior_research_manifest)
        from scripts.research.a2.evaluation.selected_performance_update import research_policy
        if package.get("policy_id", selected.LEGACY_POLICY) != policy or research_policy(prior, prior_ref) != policy:
            raise ValueError("PRIOR_RESEARCH_SAME_POLICY_REQUIRED")
    elif inputs.get("research_input_owner") is not None:
        raise ValueError("PRIOR_RESEARCH_EXPLICIT_ARGUMENT_REQUIRED")
    refs = list(inputs["refs"]) + [reference(prices_path), reference(price_inputs_path)]
    if not inputs.get("events"):
        raise ValueError("QUALIFIED_EVENT_CAPTURE_REQUIRED")
    refs.append(inputs["events"])
    verify_refs(refs)
    from scripts.research.a2.evaluation.demo_performance import reviewed_events
    open_phase = inputs.get("execution_open")
    if execution_open_manifest is not None or execution_end is not None:
        if (not open_phase or execution_open_manifest is None or execution_end is None
                or open_phase.get("manifest") != reference(execution_open_manifest)
                or open_phase.get("signal_end_date") != target_date
                or open_phase.get("execution_end_date") != execution_end
                or open_phase.get("terminal_close_available") is not False
                or open_phase.get("model_feature_eligibility_granted") is not False):
            raise ValueError("EXECUTION_OPEN_CAPTURE_BINDING_MISMATCH")
    elif open_phase:
        raise ValueError("EXECUTION_OPEN_EXPLICIT_ARGUMENTS_REQUIRED")
    bounded_stop = min(pd.Timestamp(execution_end or target_date) + pd.Timedelta(days=1), pd.Timestamp("2027-01-01")) if target_date else pd.Timestamp("2027-01-01")
    import pyarrow.parquet as pq
    event_columns = pq.read_schema(inputs["events"]["path"]).names
    event_date = "event_date" if "event_date" in event_columns else "trade_date"
    events = _capture_parquet(inputs["events"], date_column=event_date,
        start="1900-01-01", stop=bounded_stop)
    resolved_events, event_audit = reviewed_events(events, inputs.get("event_review"), refs)
    prices = _capture_parquet(reference(prices_path), date_column="trade_date",
        start="2025-11-01", stop=bounded_stop)
    prices["trade_date"] = pd.to_datetime(prices.trade_date).dt.normalize()
    if prior is not None:
        _verify_prior_price_prefix(prices,inputs,prior,reference(prices_path))
    if prices.duplicated(["ticker", "trade_date"]).any():
        raise ValueError("DUPLICATE_PRICE_IDENTITY")
    terminal = prices.trade_date.eq(pd.Timestamp(execution_end)) if open_phase else pd.Series(False, index=prices.index)
    closed = prices.loc[~terminal]
    if (not np.isfinite(closed[["open", "close"]].to_numpy(float)).all()
            or not closed[["open", "close"]].gt(0).all().all()
            or not np.isfinite(prices.open.to_numpy(float)).all() or not prices.open.gt(0).all()
            or (open_phase and (not prices.loc[terminal, ["close", "high", "low", "volume"]].isna().all().all()
                or set(prices.loc[terminal, "ticker"]) != set(open_phase["qualified_tickers"])))):
        raise ValueError("INVALID_EXECUTION_PRICE")
    target = target_date or str(prices.trade_date.max().date())
    if prior is None:
        frames, feature_refs, owner_observation, accepted = _load_sources(
            paths, selected, root, feature_paths, target_date=target)
    else:
        if feature_paths:
            raise ValueError("PRIOR_RESEARCH_FREE_FEATURE_SOURCE_FORBIDDEN")
        frames, feature_refs, owner_observation, accepted = _load_prior_sources(paths,selected,root,prior,target)
    refs.extend(feature_refs)
    refs.extend({"path": str(root / name), "sha256": sha} for name, sha in selected.FROZEN_HASHES.items())
    if sessions is None:
        sessions, calendar_ref = load_sessions(paths)
        # The calendar reader validates its immutable source bindings itself.
    if open_phase:
        from scripts.research.a2.evaluation.demo_performance_prices import execution_open_clock
        execution_open_clock(target, execution_end, sessions, open_phase["as_of_utc"])
    recovery_end = target  # Mature signal close only, including bound unexecuted missing dates.
    recovered, recovered_refs = recover_missing_features(paths, frames,
        prices.loc[prices.trade_date.le(pd.Timestamp(recovery_end))], sessions, selected,
        **({'prior_research':prior} if prior is not None else {}))
    frames.extend(recovered)
    refs.extend(recovered_refs)
    panel = score_panel(frames, selected, runtime)
    if prior is not None:
        _verify_prior_scores(panel,prior,selected)
    if owner_observation is not None:
        verify_refs([owner_observation])
        verify_accepted_scores(panel, {day: value for day, value in accepted.items() if day <= target}, selected)
        verify_refs([owner_observation])
    pairs, gap = common_clock(sessions, panel.signal_date.unique(), target, execution_end=execution_end)
    # Conservative: any unresolved event in the complete candidate universe
    # stops all three books. A later signal never fabricates event resolution.
    unreviewed = event_audit.loc[event_audit.audit_kind.eq("LARGE_RAW_MOVE_NO_VENDOR_EVENT")
        & event_audit.resolution_status.eq("UNREVIEWED")] if "audit_kind" in event_audit else event_audit.iloc[:0]
    runtime = {**runtime, "unresolved_events": set(zip(pd.to_datetime(unreviewed.event_date), unreviewed.ticker))}
    qualified, price_gap = qualify_execution_pairs(panel, prices, pairs, policy)
    if price_gap is not None:
        gap = price_gap
    if not qualified:
        raise ValueError("NO_QUALIFIED_EXECUTION_WINDOW:" + str(gap))
    pairs = qualified
    output = Path(output_dir).resolve()
    if output.is_relative_to(root.resolve()):
        raise ValueError("OUTPUT_MUST_NOT_MUTATE_FROZEN_SOURCE")
    output.mkdir(parents=True, exist_ok=False)
    producer_ref = _freeze_producer_vintage(output, producer_observation, producer_bytes)
    refs.append(producer_ref)
    with selected._isolated_imports(root):
        replay, e5_ref = load_frozen_close_clock_replay(root)
        refs.append(e5_ref)
        strategy_data = {}
        while True:
            completed = {}
            try:
                for sid in (*IDS, *(("LEGACY_HGB_DIAG_5", "LEGACY_HGB_FACTOR_5") if include_legacy else ())):
                    base_sid = sid.removeprefix("LEGACY_")
                    policy_runtime = {**runtime, "policy": selected.LEGACY_POLICY} if sid.startswith("LEGACY_") else runtime
                    name = "RAW" if sid == "RAW_A2" else sid
                    spec = None if sid == "RAW_A2" else runtime["optimizer"].SPECS[base_sid]
                    completed[sid] = replay_common(replay, name, spec, panel, prices, policy_runtime, pairs)
                break
            except HeldPriceMissing as exc:
                gap = {"signal_date": str(exc.signal.date()), "execution_date": str(exc.execution.date()),
                       "reason": "HELD_CORPORATE_ACTION_UNRESOLVED" if isinstance(exc, HeldEventUnresolved)
                           else "HELD_EXECUTION_PRICE_MISSING", "keys": exc.keys}
                pairs = [(signal, execution) for signal, execution in pairs if execution < exc.execution]
                if not pairs:
                    raise ValueError("NO_QUALIFIED_EXECUTION_WINDOW:" + str(gap)) from exc
        for sid in completed:
            result, decisions = completed[sid]
            ledger = result.daily
            expected = pd.DatetimeIndex([execution for _, execution in pairs])
            if not pd.DatetimeIndex(ledger.execution_date).equals(expected):
                raise ValueError("COMMON_EXECUTION_CLOCK_CHANGED:" + sid)
            daily_path, targets_path = output / (sid.lower() + "_daily.parquet"), output / (sid.lower() + "_targets.parquet")
            ledger.to_parquet(daily_path, index=False)
            decisions.to_parquet(targets_path, index=False)
            daily = selected._daily_rows(ledger)
            targets = []
            for day, rows in decisions.groupby("signal_date"):
                records = [{"ticker": row.ticker, "target_weight": float(row.target_weight),
                            "weight_before": float(row.signal_close_weight),
                            "action": selected._action(row.target_weight, row.signal_close_weight)}
                           for row in rows.itertuples()]
                targets.append({"signal_date": str(day.date()), "rows": records})
            strategy_data[sid] = {"label": "Raw A2" if sid == "RAW_A2" else selected.LABELS[sid.removeprefix("LEGACY_")],
                "daily": daily, "targets": targets,
                "summary": {"end_nav": daily[-1]["nav"], "cumulative_return": daily[-1]["nav"] - 1,
                    "max_drawdown": float((ledger.nav / ledger.nav.cummax() - 1).min()),
                    "turnover": float(ledger.turnover.sum()),
                    "mean_cash": float(ledger.cash_weight.mean()), "days": len(daily)},
                "outputs": {"daily": reference(daily_path), "targets": reference(targets_path)}}
    verify_refs(refs)
    if owner_observation is not None:
        verify_refs([owner_observation])
    verify_refs([producer_observation])
    period = {"start": str(pairs[0][1].date()), "end": str(pairs[-1][1].date()), "days": len(pairs),
              "price_basis": BASIS, "decision_clock": "SIGNAL_CLOSE_NEXT_SESSION_OPEN"}
    manifest = {"schema_version": 1, "source_id": "NEW_PIT_COMPARISON", "status": "PARTIAL" if gap else "READY",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "performance_period": period, "requested_end_date": execution_end or target, "blocked_next": gap,
        **({"signal_end_date": target, "execution_open": open_phase} if open_phase else {}),
        "strategies": {sid: strategy_data[sid] for sid in IDS},
        "comparisons": {sid: value for sid, value in strategy_data.items() if sid not in IDS},
        "policy_id": policy, "source_refs": refs, "model_fit_calls": 0,
        "preserved_frozen_qfq_root": str(root),
        "producer_ref": producer_ref,
        "canonical_producer_observation": producer_observation,
        "initial_cash_coordinate": 1.0,
        # Observed mutable pointer; immutable accepted snapshot/receipt refs above establish authority.
        "selected_package_observation": owner_observation,
        "shared_scores_historical": [record for day, group in panel.groupby("signal_date")
            for record in selected._score_rows(group, signal_date=str(day.date()))],
        "broker_action_allowed": False, "cost_one_way": .0005,
        "limitations": ["Independent descriptive PIT comparison; original frozen QFQ replay is unchanged.",
                        "Same frozen scorer/risk parameters and cash-start share/cash engine; policy_id states eligible-candidate wiring."]}
    published = _write_extension_manifest(output / "manifest.json", manifest)
    if prior is not None:
        from scripts.research.a2.evaluation.selected_performance_update import verify_direct_research_prefix
        verify_direct_research_prefix(prior,published)
    return published
