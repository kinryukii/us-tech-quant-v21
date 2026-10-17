"""Current, no-fit TOP100 input continuation for the original paper consumers.

The historical source and its availability/completeness limitations are retained.
Current pool identity is bound to the original consensus snapshot and the current
accepted identity mapping. New report quarters require a qualified source refresh;
this adapter never substitutes the original per-manager union for the Top100.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

TASK = "DEMO_FIVE_STRATEGY_PAPER_20261013_R1"
BASE_FLAGS_REF = {"path": "D:/us-tech-quant-backtests/A_ALL_REPAIR_AND_CONSENSUS_SENSITIVITY_20261011_R1/20261010T155614+0000_8a89315b/derived/raw_sensitivity/TOP100/inference/attempt_007/flags.parquet", "sha256": "8598030725df0758336ca6e2a7b559f4c203d0d106e1e79a1064437a2b1dfa06"}
BUNDLE = Path("D:/us-tech-quant-backtests/A_ALL_REPAIR_AND_CONSENSUS_SENSITIVITY_20261011_R1/20261010T155614+0000_8a89315b/derived/consensus_inputs/variants/TOP100/SOURCE_BUNDLE_R4.json")


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_reference(ref):
    path = Path(ref["path"]).resolve()
    if digest(path) != ref["sha256"]:
        raise ValueError("CURRENT_CONSENSUS_SOURCE_HASH_CHANGED:" + path.name)
    return path


def json_document(path, max_bytes=16 * 1024 * 1024):
    path = Path(path)
    if path.stat().st_size > max_bytes:
        raise ValueError("CURRENT_CONSENSUS_DOCUMENT_TOO_LARGE")
    result = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(result, dict):
        raise ValueError("CURRENT_CONSENSUS_DOCUMENT_REQUIRED")
    return result


def bind_pool(source_schedule, source_members, mapped_members, signal_date, current_quarter):
    """Pure current identity join; no coverage-based reranking or replacements."""
    import pandas as pd
    signal = pd.Timestamp(signal_date)
    if signal < pd.Timestamp("2026-01-01") or signal >= pd.Timestamp("2027-01-01"):
        raise ValueError("CURRENT_CONSENSUS_CALENDAR_BOUNDARY")
    eligible = source_schedule.loc[pd.to_datetime(source_schedule.effective_at, utc=True) <=
        signal.tz_localize("America/New_York") + pd.Timedelta(hours=16)].copy()
    if eligible.empty:
        raise ValueError("CURRENT_CONSENSUS_SNAPSHOT_UNAVAILABLE")
    original = eligible.sort_values("effective_at").iloc[-1]
    if original.quarter != current_quarter:
        raise ValueError("CURRENT_CONSENSUS_QUALIFIED_NEW_QUARTER_SOURCE_REQUIRED")
    chosen = source_members.loc[source_members.snapshot_id.eq(original.snapshot_id)].copy()
    if len(chosen) != 100 or chosen.cusip.duplicated().any():
        raise ValueError("CURRENT_CONSENSUS_EXACT_TOP100_REQUIRED")
    mapping = mapped_members.copy()
    if "cusip" not in mapping:
        mapping["cusip"] = mapping.security_id.astype(str)
    for key in ("cusip", "ticker", "security_id"):
        mapping[key] = mapping[key].astype(str).str.strip()
    if mapping.cusip.duplicated().any() or mapping.ticker.duplicated().any():
        raise ValueError("CURRENT_CONSENSUS_MAPPING_AMBIGUOUS")
    joined = chosen.merge(mapping[["cusip", "ticker", "security_id"]], on="cusip", how="left", validate="one_to_one")
    missing = joined.loc[joined.ticker.isna() | joined.security_id.isna(), "cusip"].astype(str).tolist()
    if missing:
        raise ValueError("CURRENT_CONSENSUS_MAPPING_MISSING:" + ",".join(missing))
    if joined.ticker.duplicated().any() or joined.security_id.duplicated().any():
        raise ValueError("CURRENT_CONSENSUS_MAPPED_IDENTITY_DUPLICATE")
    source_id = str(original.snapshot_id)
    snapshot = source_id + "__" + signal.strftime("%Y-%m-%d")
    joined["source_snapshot_id"] = source_id
    joined["snapshot_id"] = snapshot
    schedule = pd.DataFrame([dict(snapshot_id=snapshot, source_snapshot_id=source_id,
        universe_id="CONSENSUS_TOP100_CURRENT_NO_FIT", quarter=current_quarter,
        effective_date=signal.strftime("%Y-%m-%d"), snapshot_effective_date=signal.strftime("%Y-%m-%d"),
        source_effective_at=str(original.effective_at), universe_member_count=100,
        mapped_count=100, institution_count=int(original.institution_count))])
    ledger = pd.DataFrame([dict(target_date=signal, snapshot_id=snapshot)])
    identity = joined[["ticker", "security_id"]].copy()
    identity["signal_date"] = signal
    identity["is_max_group"] = True
    return schedule, joined, ledger, identity



def source_input_fields(selected):
    """Project only accepted daily mathematical inputs, never chart results."""
    from scripts.research.a2.data.consensus_account_inputs import _JsonProjection
    selected = Path(selected)
    if selected.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("CURRENT_CONSENSUS_DOCUMENT_TOO_LARGE")
    with selected.open("rb") as stream:
        result = _JsonProjection(stream).metadata_fields({"status", "data_date", "report_path", "generated_at", "universe", "frozen_raw32_features"})
    # The original saved acquisition-input binding is larger than navigation
    # metadata. The accepted source holds about 9 MiB of inputs; decode this
    # exact field separately with the existing 16 MiB document bound.
    with selected.open("rb") as stream:
        reader = _JsonProjection(stream)
        reader.descend(("acquisitions",))
        result["acquisitions"] = reader.scalar(limit=16 * 1024 * 1024)
    for key, names in (("native_current_tail", {"result_count"}),
            ("native_market_publication", {"status", "target_date", "all_old_dates_preserved", "published_intervals", "requested_keys", "raw_reached_target", "request_sha256"})):
        with selected.open("rb") as stream:
            reader = _JsonProjection(stream)
            try:
                reader.descend((key,))
            except ValueError as exc:
                if str(exc) != "SOURCE_JSON_SELECTED_PATH_MISSING":
                    raise
                continue
            result[key] = reader.metadata_fields(names)
    return result

def _daily_capture_paths(paths, signal, deadline):
    """Only UTC run prefixes intersecting the declared signal/deadline interval."""
    import pandas as pd
    first=pd.Timestamp(signal).tz_localize("America/New_York")+pd.Timedelta(hours=16)
    last=pd.Timestamp(deadline)
    if last.tzinfo is None or last<first:
        raise ValueError("CURRENT_CONSENSUS_HISTORY_CLOCK_REQUIRED")
    root=paths.daily_root/"A2_today_recommendation"
    prefixes=pd.date_range(first.tz_convert("UTC").normalize(),last.tz_convert("UTC").normalize(),freq="D").strftime("%Y%m%d")
    seen=set()
    for prefix in prefixes:
        for capture in (root/"history").glob(prefix+"*.json"):
            resolved=capture.resolve()
            if resolved not in seen:
                seen.add(resolved);yield resolved
        for folder in (root/"runs").glob(prefix+"T*"):
            capture=(folder/"report.json").resolve()
            if capture.is_file() and capture not in seen:
                seen.add(capture);yield capture


def accepted_daily_report_metadata(paths, signal, *, deadline):
    """Original accepted daily custody, projected without acquisition/price data.

    This stricter metadata view requires the existing accepted_source and the
    existing accepted_inputs rehab ref. A legacy READY record without those
    refs remains unavailable to this new consumer, not newly certified.
    """
    import pandas as pd
    from scripts.common.json_projection import metadata_fields,_parser_type
    runs=(paths.daily_root/"A2_today_recommendation/runs").resolve()
    captures=list(_daily_capture_paths(paths,signal,deadline))
    if len(captures)>128:raise ValueError("CURRENT_CONSENSUS_HISTORY_CAPTURE_LIMIT")
    result=[]
    for capture in captures:
        if capture.stat().st_size>32*1024*1024:continue
        with capture.open("rb") as h:
            meta=metadata_fields(h,{"status","data_date","generated_at","accepted_source","accepted_inputs"})
        if meta.get("status")!="READY" or meta.get("data_date")!=signal:
            continue
        source_ref=meta.get("accepted_source");inputs=meta.get("accepted_inputs")
        if not isinstance(source_ref,dict) or not isinstance(inputs,list):continue
        source=read_reference(source_ref)
        if source.name!="recommendation_source.json" or source.parent.parent!=runs:
            raise ValueError("CURRENT_CONSENSUS_ACCEPTED_SOURCE_LOCATION_CHANGED")
        with source.open("rb") as h:
            origin=metadata_fields(h,{"status","data_date","generated_at"})
        if origin.get("status")!="READY" or origin.get("data_date")!=signal:
            raise ValueError("CURRENT_CONSENSUS_ACCEPTED_SOURCE_DATE_CHANGED")
        received=pd.Timestamp(origin.get("generated_at"))
        if received.tzinfo is None or received<pd.Timestamp(signal).tz_localize("America/New_York")+pd.Timedelta(hours=16):
            raise ValueError("CURRENT_CONSENSUS_ACCEPTED_SOURCE_CLOCK_CHANGED")
        rehab=[ref for ref in inputs if isinstance(ref,dict) and Path(ref.get("path","")).resolve()==source.parent/"rehab_receipt.json"]
        if len(rehab)!=1:continue
        read_reference(rehab[0])
        with source.open("rb") as h:
            parser=_parser_type()(h)
            try:
                parser.descend(("universe",))
                universe=parser.metadata_fields({"report_path","universe_members_sha256"})
            except ValueError:continue
        if not universe.get("report_path") or not universe.get("universe_members_sha256"):continue
        mapping=dict(path=str(Path(universe["report_path"]).parent/"mapped_members.parquet"),sha256=universe["universe_members_sha256"])
        read_reference(mapping)
        result.append(dict(signal_date=signal,generated_at=origin["generated_at"],capture_ref=dict(path=str(capture),sha256=digest(capture)),
            source_ref=source_ref,rehab_ref=rehab[0],mapping_ref=mapping))
    # Multiple final captures of one immutable source are the same custody.
    unique={row["source_ref"]["sha256"]:row for row in result}
    return sorted(unique.values(),key=lambda row:(row["generated_at"],row["source_ref"]["path"]))


def _historical_report(paths, signal):
    from scripts.research.a2.data.consensus_account_inputs import _JsonProjection
    import pandas as pd
    end=pd.Timestamp(signal).tz_localize("America/New_York")+pd.Timedelta(days=1,hours=16)
    captures=list(_daily_capture_paths(paths,signal,end))
    candidates = []
    for path in captures:
        if path.parent != (paths.daily_root / "A2_today_recommendation/history").resolve():
            continue
        if path.stat().st_size > 32 * 1024 * 1024:
            continue
        with path.open("rb") as stream:
            meta = _JsonProjection(stream).metadata_fields({"status", "data_date", "report_path", "generated_at"})
        if meta.get("status") == "READY" and meta.get("data_date") == signal:
            candidates.append((meta.get("generated_at", ""), Path(meta.get("report_path", path))))
    if not candidates:
        # A completed update can remain the last canonical run without a history
        # copy. Require its original immutable accepted-source binding.
        runs = paths.daily_root / "A2_today_recommendation" / "runs"
        for report in captures:
            folder=report.parent
            if folder.parent != runs.resolve():
                continue
            if not report.is_file() or report.stat().st_size > 32 * 1024 * 1024:
                continue
            with report.open("rb") as stream:
                meta = _JsonProjection(stream).metadata_fields({"status", "data_date", "report_path", "generated_at", "accepted_source"})
            accepted = meta.get("accepted_source")
            if meta.get("status") != "READY" or meta.get("data_date") != signal or not isinstance(accepted, dict):
                continue
            source = read_reference(accepted)
            if source != (folder / "recommendation_source.json").resolve():
                raise ValueError("CURRENT_CONSENSUS_ACCEPTED_SOURCE_LOCATION_CHANGED")
            with source.open("rb") as stream:
                origin = _JsonProjection(stream).metadata_fields({"status", "data_date"})
            if origin.get("status") != "READY" or origin.get("data_date") != signal:
                raise ValueError("CURRENT_CONSENSUS_ACCEPTED_SOURCE_DATE_CHANGED")
            candidates.append((meta.get("generated_at", ""), source))
    if not candidates:
        raise ValueError("CURRENT_CONSENSUS_DAILY_SOURCE_GAP:" + signal)
    selected = max(candidates, key=lambda row: row[0])[1]
    return source_input_fields(selected)


def _feature_frame(paths, report, signal, work, *, allow_raw_recovery=True):
    """Reuse the accepted feature owner; reconstruction is current-state input only."""
    import pandas as pd
    import pyarrow.parquet as pq
    binding = report.get("frozen_raw32_features")
    recovered = work / "raw32" / signal / "frozen_raw32_features_binding.json"
    native_route = (binding is None and report.get("native_market_publication", {}).get("status") == "PUBLISHED")
    if native_route:
        # Preserve the earlier snapshot from the un-routed saved receipt.
        recovered = recovered.parent / "native_publication_r1" / recovered.name
    if not binding and recovered.exists():
        binding = json_document(recovered)
    if not binding or binding.get("status") != "READY":
        if not allow_raw_recovery:
            raise ValueError("CURRENT_CONSENSUS_ACCEPTED_RAW32_REQUIRED_NO_RECOVERY:" + signal)
        from scripts.daily_recommendation_inputs import load_frozen_binding
        from scripts.daily_recommendation import predict_current, prediction_after_native_publication
        from scripts.research.a2.inference.historical_top40 import load_sessions
        from scripts.storage.storage_r2a import DataStore
        original_binding = load_frozen_binding(paths.repo_root)
        universe = dict(report["universe"])
        universe["members"] = pq.read_table(read_reference({"path": str(Path(universe["report_path"]).parent / "mapped_members.parquet"), "sha256": universe["universe_members_sha256"]})).to_pandas().to_dict("records")
        universe["current"] = True  # Only the exact already-accepted report's universe.
        sessions, _ = load_sessions(paths)
        rehab = json_document(Path(report["report_path"]).parent / "rehab_receipt.json")
        output = recovered.parent
        from scripts.common.storage_paths import assert_safe_output_path
        assert_safe_output_path(output, kind="daily", paths=paths)
        output.mkdir(parents=True, exist_ok=True)
        acquired = report["acquisitions"]
        routed = prediction_after_native_publication(acquired, report.get("native_market_publication", {}),
            report.get("native_current_tail", {}).get("result_count", 0), signal)
        if native_route and routed is acquired:
            raise ValueError("CURRENT_CONSENSUS_NATIVE_PUBLICATION_ROUTING_PROOF_REQUIRED")
        predict_current(original_binding, universe, signal, sessions, routed, DataStore(paths), rehab, output_dir=output)
        binding = json_document(recovered)
    if binding.get("status") != "READY" or binding.get("signal_date") != signal:
        raise ValueError("CURRENT_CONSENSUS_FROZEN_RAW32_SNAPSHOT_REQUIRED:" + signal)
    path = read_reference(binding)
    frame = pq.read_table(path, columns=binding["columns"], filters=[("trade_date", "==", pd.Timestamp(signal).to_pydatetime())]).to_pandas()
    return frame, binding


def _prepare_current_inputs(paths, *, current_report, run_dir, reuse_only=False, allow_raw_recovery=True):
    """One existing daily update owns this stage; no acquisition, fitting or orders."""
    from scripts.research.a2.inference import consensus_paper
    if current_report.get("status") != "READY":
        raise ValueError("CURRENT_CONSENSUS_READY_DAILY_SOURCE_REQUIRED")
    signal = str(current_report["data_date"])
    declared = current_report.get("frozen_raw32_features", {})
    if declared.get("status") != "READY" or declared.get("signal_date") != signal or declared.get("frozen_model_sha256") != "4f7eff07021bef084b0329dac8dabc31e9391c7c4945eb2955dc6c1339dcea0b" or declared.get("feature_source_ref", {}).get("sha256") != "fd4fe78d27bfbf57c89343d60550366ccf7fcbf3d6a65e7ef66f28405d050c19":
        # Synthetic/foreign daily sources fail before accessing real frozen inputs.
        raise ValueError("CURRENT_CONSENSUS_EXACT_RAW32_DAILY_BINDING_REQUIRED")
    accepted = paths.daily_root / "A2_consensus_paper" / "latest.json"
    if accepted.exists():
        pointer = json_document(accepted)
        identity = consensus_paper.metadata(pointer, ("status", "signal_date"))
        if identity.get("signal_date") == signal and identity.get("status") == "READY":
            verified, publication_ref = consensus_paper.load_publication(paths, signal, datetime.now(timezone.utc).isoformat())
            if verified.get("status") != "READY":
                raise ValueError("CURRENT_CONSENSUS_ACCEPTED_BASE_NOT_READY")
            extension = json_document(read_reference(verified["source_extension_ref"]))
            today = [row for row in extension["current_day_proofs"] if row["signal_date"] == signal]
            if len(today) != 1 or today[0]["feature_ref"].get("sha256") != declared["sha256"]:
                raise ValueError("CURRENT_CONSENSUS_ACCEPTED_SAME_DAY_INPUT_CHANGED")
            return dict(status="READY", signal_date=signal, publication=publication_ref, reused=True)
    if reuse_only:
        raise ValueError("CURRENT_CONSENSUS_ACCEPTED_SOURCE_REQUIRED_FOR_RESUME")
    source_ref = dict(path=str(BUNDLE), sha256=consensus_paper.BUNDLE_SHA)
    prior = paths.daily_root / "A2_consensus_paper" / "latest_flags.json"
    saved = json_document(prior) if prior.exists() else None
    if saved is not None and saved.get("signal_date") == signal:
        # Construction may have committed before guarded publication ran. Reuse
        # that exact checkpoint through the original consumer's qualification.
        if saved.get("status") != "READY" or saved.get("source_bundle_ref") != source_ref:
            raise ValueError("CURRENT_CONSENSUS_PREPARED_SOURCE_CHANGED")
        import pandas as pd
        proof = consensus_paper.validate_extension(saved["source_extension_ref"], saved["flags_ref"],
            source_ref, pd.Timestamp(signal), pd.Timestamp(datetime.now(timezone.utc)))
        read_reference(saved["flags_ref"])
        today = [row for row in proof["current_day_proofs"] if row["signal_date"] == signal]
        universe = current_report["universe"]
        mapping_ref = dict(path=str(Path(universe["report_path"]).parent / "mapped_members.parquet"),
            sha256=universe["universe_members_sha256"])
        if (len(today) != 1 or today[0]["feature_ref"] != declared or today[0]["mapping_ref"] != mapping_ref
                or saved.get("decision_as_of") != proof["decision_as_of"]):
            raise ValueError("CURRENT_CONSENSUS_PREPARED_ACCEPTED_INPUT_CHANGED")
        return dict(flags_ref=saved["flags_ref"], source_bundle_ref=source_ref, signal_date=signal,
            decision_as_of=proof["decision_as_of"], source_extension_ref=saved["source_extension_ref"])
    # An accepted same-day source needs only its sealed bindings. Load the
    # feature/ranking stack only for genuinely new daily rows.
    import numpy as np
    import pandas as pd
    import pyarrow.parquet as pq
    from scripts.common.storage_paths import assert_safe_output_path
    from scripts.daily_recommendation import save
    from scripts.research.a2.inference.historical_top40 import ranked_predictions, load_sessions
    from scripts.research.a2.inference.stateful_test_inputs import assemble_flags, FEATURES
    observed = datetime.now(timezone.utc)
    if pd.Timestamp(signal).tz_localize("America/New_York") + pd.Timedelta(hours=16) > observed:
        raise ValueError("CURRENT_CONSENSUS_COMPLETED_CLOSE_REQUIRED")
    # The consumer holds the exact full original bundle pin.
    source = json_document(read_reference(source_ref))
    if source.get("pool_variant_id") != "TOP100" or source.get("selection_rule") != "MANAGER_COUNT_WEIGHT_SUM" or source.get("cohort_count") != 25 or source.get("excluded_manager") is not None:
        raise ValueError("CURRENT_CONSENSUS_FROZEN_POOL_CONTRACT_CHANGED")
    source_schedule = pq.read_table(read_reference(source["source_schedule_ref"])).to_pandas()
    source_members = pq.read_table(read_reference(source["source_members_ref"])).to_pandas()
    flags_ref = dict(BASE_FLAGS_REF)
    prior_extension_ref = None
    if saved is not None:
        if saved.get("status") == "READY" and saved.get("source_bundle_ref") == source_ref and saved.get("signal_date", "9999") < signal:
            flags_ref = saved["flags_ref"]
            prior_extension_ref = saved["source_extension_ref"]
    flags_path = read_reference(flags_ref)
    from scripts.daily_recommendation_inputs import load_frozen_binding, MODEL_SHA256
    frozen_binding = load_frozen_binding(paths.repo_root)
    component = frozen_binding["components"]["ALPHA"]
    frozen_model = next({"path": item["path"], "sha256": item["sha256"]} for item in component["artifacts"] if item["artifact_id"] == "model")
    feature_source_ref = next({"path": item["path"], "sha256": item["sha256"]} for item in component["artifacts"] if item["artifact_id"] == "source")
    if frozen_model["sha256"] != MODEL_SHA256 or feature_source_ref["sha256"] != "fd4fe78d27bfbf57c89343d60550366ccf7fcbf3d6a65e7ef66f28405d050c19":
        raise ValueError("CURRENT_CONSENSUS_FROZEN_RAW_OWNER_CHANGED")
    footer = pq.ParquetFile(flags_path)
    from scripts.research.a2.training import stateful_inputs, stateful_decision as decision
    allowed = list(dict.fromkeys((*stateful_inputs.PRED_FLAGS, *FEATURES, *decision.PRED_EXTRA)))
    columns = [name for name in allowed if name in footer.schema_arrow.names]
    flags = pq.read_table(flags_path, columns=columns, filters=[("signal_date", ">=", pd.Timestamp("2026-01-01").to_pydatetime()), ("signal_date", "<=", pd.Timestamp(signal).to_pydatetime())]).to_pandas()
    last = pd.to_datetime(flags.signal_date).max()
    sessions, calendar = load_sessions(paths)
    tail = [day for day in sessions if last < pd.Timestamp(day) <= pd.Timestamp(signal)]
    if not tail or tail[-1] != signal:
        if str(last.date()) != signal:
            raise ValueError("CURRENT_CONSENSUS_CALENDAR_GAP")
    work = paths.daily_root / "A2_consensus_paper" / "current_source" / signal
    assert_safe_output_path(work, kind="daily", paths=paths)
    proofs, pieces = [], [flags]
    for day in tail:
        report = current_report if day == signal else _historical_report(paths, day)
        if report.get("status") != "READY" or report.get("data_date") != day:
            raise ValueError("CURRENT_CONSENSUS_ACCEPTED_DAY_MISMATCH:" + day)
        universe = report["universe"]
        mapping_ref = dict(path=str(Path(universe["report_path"]).parent / "mapped_members.parquet"), sha256=universe["universe_members_sha256"])
        mapped = pq.read_table(read_reference(mapping_ref)).to_pandas()
        schedule, members, ledger, identity = bind_pool(source_schedule, source_members, mapped, day, universe["quarter"])
        frame, feature_ref = _feature_frame(paths, report, day, work,
            **({"allow_raw_recovery": False} if not allow_raw_recovery else {}))
        if list(FEATURES) != [name for name in frame.columns if name in FEATURES]:
            raise ValueError("CURRENT_CONSENSUS_ORDERED_RAW32_CHANGED")
        frame = frame[["trade_date", "ticker", *FEATURES]]
        if not np.isfinite(frame[list(FEATURES)].to_numpy(float)).all():
            raise ValueError("CURRENT_CONSENSUS_NONFINITE_RAW32")
        if feature_ref.get("frozen_model_sha256") != frozen_model["sha256"] or feature_ref.get("feature_source_ref") != feature_source_ref:
            raise ValueError("CURRENT_CONSENSUS_RAW_MODEL_IDENTITY_CHANGED")
        models = {"artifacts": {"2026": {**frozen_model, "labelmax": "2025-12-31"}}}
        rank, coverage = ranked_predictions(frame, schedule, members, ledger, models, list(FEATURES))
        # The original owner retains the fixed 100-member denominator while
        # ranking only qualified mathematical inputs (93 in accepted Oct8).
        # Missing members stay unranked; the pool is never replaced or expanded.
        ordered_pool = members.sort_values("consensus_rank").security_id.astype(str).tolist()
        ranked_pool = rank.sort_values("rank").security_id.astype(str).tolist()
        unranked_pool = [sid for sid in ordered_pool if sid not in set(ranked_pool)]
        coverage_status = "READY" if len(rank) == 100 else "PARTIAL"
        if (not 40 <= len(rank) <= 100 or len(coverage) != 1
                or int(coverage.iloc[0].universe_member_count) != 100
                or int(coverage.iloc[0].eligible_count) != len(rank)
                or coverage.iloc[0].status != coverage_status
                or len(set(ranked_pool)) != len(rank)
                or not set(ranked_pool) <= set(ordered_pool)
                or set(rank["rank"]) != set(range(1, len(rank) + 1))):
            raise ValueError("CURRENT_CONSENSUS_ORIGINAL_QUALIFIED_RANK_REQUIRED")
        day_flags = assemble_flags(frame, rank, identity)
        pieces.append(day_flags)
        proofs.append(dict(signal_date=day, source_snapshot_id=str(members.source_snapshot_id.iloc[0]), mapping_ref=mapping_ref,
            feature_ref=feature_ref, ordered_pool_security_ids=ordered_pool, ranked_pool_security_ids=ranked_pool,
            unranked_pool_security_ids=unranked_pool, input_coverage_status=coverage_status,
            current_mapping_is_not_historical_pit_authority=True, rows=len(day_flags), ranked_rows=len(rank)))
    combined = pd.concat(pieces, ignore_index=True)
    if combined.duplicated(["signal_date", "ticker"]).any():
        raise ValueError("CURRENT_CONSENSUS_DUPLICATE_FLAGS")
    work.mkdir(parents=True, exist_ok=True)
    output = work / "flags.parquet"
    if output.exists():
        old = pq.read_table(output, columns=list(combined)).to_pandas()
        if not old.equals(combined):
            raise ValueError("CURRENT_CONSENSUS_PRESERVE_EXISTING_FLAGS")
    else:
        combined.to_parquet(output, index=False)
    published_ref = dict(path=str(output.resolve()), sha256=digest(output))
    extension = dict(schema="CURRENT_CONSENSUS_PAPER_SOURCE_EXTENSION_R1", task_id=TASK, status="READY",
        signal_date=signal, observed_at_utc=observed.isoformat(), decision_as_of=observed.isoformat(),
        source_bundle_ref=source_ref, parent_flags_ref=dict(BASE_FLAGS_REF), flags_ref=published_ref, raw_model_ref=frozen_model, feature_source_ref=feature_source_ref, new_fit=0,
        selection_rule="MANAGER_COUNT_WEIGHT_SUM", pool_variant_id="TOP100", cohort_count=25, current_day_proofs=proofs,
        parent_source_role=source.get("source_role"), parent_source_completeness_unknown=source.get("source_completeness_unknown"),
        parent_historical_available_at_bound=source.get("historical_available_at_bound"), execution_admission_inherited=False)
    if prior_extension_ref is not None:
        extension.update(continued_flags_ref=flags_ref, prior_source_extension_ref=prior_extension_ref)
    receipt = work / "source_extension.json"
    if receipt.exists():
        prior_proof = json_document(receipt)
        invariant = {k:v for k,v in extension.items() if k not in {"observed_at_utc", "decision_as_of"}}
        previous_invariant = {k:v for k,v in prior_proof.items() if k not in {"observed_at_utc", "decision_as_of"}}
        if previous_invariant != invariant:
            raise ValueError("CURRENT_CONSENSUS_PRESERVE_EXISTING_SOURCE_PROOF")
        extension = prior_proof
        observed = datetime.fromisoformat(extension["decision_as_of"])
    else:
        save(receipt, extension)
    save(paths.daily_root / "A2_consensus_paper" / "latest_flags.json", {**extension, "source_extension_ref": dict(path=str(receipt), sha256=digest(receipt))})
    return dict(flags_ref=published_ref, source_bundle_ref=source_ref, signal_date=signal,
        decision_as_of=observed.isoformat(), source_extension_ref=dict(path=str(receipt), sha256=digest(receipt)))


def refresh_current_inputs(paths, *, current_report, run_dir, reuse_only=False, allow_raw_recovery=True):
    """Release construction frames before the original guarded publication stage."""
    import gc
    from scripts.research.a2.inference import consensus_paper
    prepared = _prepare_current_inputs(paths, current_report=current_report, run_dir=run_dir,
        **({"reuse_only": True} if reuse_only else {}),
        **({"allow_raw_recovery": False} if not allow_raw_recovery else {}))
    if reuse_only:
        # Ordinary same-day refresh is a reader. Optional recovery remains an
        # explicit producer action and cannot replace a READY cache with BLOCKED.
        clock = datetime.now(timezone.utc).isoformat()
        if not prepared.get("reused"):
            raise ValueError("CURRENT_CONSENSUS_ACCEPTED_SOURCE_REQUIRED_FOR_RESUME")
        base, base_ref = consensus_paper.load_publication(paths, prepared["signal_date"], clock)
        if (base_ref != prepared["publication"] or base.get("status") != "READY"
                or base.get("signal_date") != prepared["signal_date"]):
            raise ValueError("CURRENT_CONSENSUS_ACCEPTED_BASE_CHANGED")
        for ref in base["input_refs"].values():
            consensus_paper.verify(ref)
        try:
            current, ref = consensus_paper.load_publication(paths, prepared["signal_date"], clock, paper_current=True)
            if current.get("base_publication_ref") != base_ref or current.get("duration_publication_ref") != ref:
                raise ValueError("CURRENT_CONSENSUS_ACCEPTED_DURATION_BASE_CHANGED")
            status = current["strategy_status"]["R6_DURATION_TREE"]
            if status["status"] == "READY":
                frame = consensus_paper._qualified_duration_frame(paths, current)
                del frame
            elif status["status"] != "BLOCKED":
                raise ValueError("CURRENT_CONSENSUS_ACCEPTED_DURATION_STATUS_REQUIRED")
            extension = dict(status=status["status"], publication_ref=ref,
                decision_as_of=current["decision_as_of"], reused=True, reason=status.get("reason"))
        except Exception as exc:
            extension = dict(status="BLOCKED", publication_ref=None, decision_as_of=None,
                reused=False, reason=(type(exc).__name__ + ":" + str(exc))[:1024])
        return dict(status=base["status"], signal_date=base["signal_date"], flags_ref=base["flags_ref"],
            source_extension_ref=base["source_extension_ref"], publication={**base, "paper_current_extension": extension})
    if prepared.get("reused"):
        # Reuse the immutable three-method publication. An optional newly
        # connected method must not be hidden forever behind that old READY.
        base = consensus_paper.metadata(prepared["publication"], {
            "flags_ref", "source_bundle_ref", "source_extension_ref", "signal_date", "decision_as_of"})
    else:
        base = prepared
    # Construction can leave cyclic temporary frames alive. Release them
    # before the optional builder's resource check, not just before publishing.
    gc.collect()
    consensus_paper._release_arrow_cache()
    r6_clock = datetime.now(timezone.utc).isoformat()
    try:
        from scripts.research.a2.inference.current_r6_probes import prepare_current_r6_probes
        r6_source = prepare_current_r6_probes(paths, flags_ref=base["flags_ref"],
            source_bundle_ref=base["source_bundle_ref"], signal_date=base["signal_date"],
            decision_as_of=r6_clock, current_report=current_report, run_dir=run_dir)
    except Exception as exc:
        # One optional producer failure cannot take the original methods down.
        r6_source = dict(schema="CURRENT_R6_PROBE_SOURCE_V1", status="BLOCKED",
            signal_date=base["signal_date"], decision_as_of=r6_clock,
            probe_ref=None, qualification_ref=None, reason=type(exc).__name__)
    # The builder scope has ended; only sealed references cross this boundary.
    # Keep the original complete history, transforms and resource gate unchanged.
    gc.collect()
    consensus_paper._release_arrow_cache()
    result = consensus_paper.publish_inputs(paths, **base, r6_probe_source=r6_source)
    return dict(status=result.get("status", "READY"), signal_date=base["signal_date"],
        flags_ref=base["flags_ref"], source_extension_ref=base["source_extension_ref"], publication=result)
