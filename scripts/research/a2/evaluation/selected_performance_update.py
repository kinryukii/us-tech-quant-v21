"""Publish one verified common replay window alongside current selected targets."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import json
import uuid



def research_policy(manifest, manifest_ref=None):
    """Recognize the accepted pre-policy producer format; never relabel unknowns.

    This checks the original captured producer's qualification seam, not arbitrary
    Python semantics. Explicit modern policy metadata always owns its identity.
    """
    from scripts.research.a2.portfolio import selected_hgb as selected
    if "policy_id" in manifest:
        policy = manifest["policy_id"]
        if policy not in {selected.LEGACY_POLICY, selected.DIRECT_POLICY}:
            raise ValueError("RESEARCH_EXPLICIT_POLICY_INVALID")
        return policy
    from scripts.research.a2.evaluation import three_strategy_extension as extension
    import ast
    import hashlib
    if (type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1
            or manifest.get("source_id") != "NEW_PIT_COMPARISON"
            or not isinstance(manifest_ref, dict) or set(manifest_ref) != {"path", "sha256"}):
        raise ValueError("LEGACY_RESEARCH_ORIGINAL_SCHEMA_BINDING_REQUIRED")
    stored, observed = extension._capture_json(manifest_ref["path"], manifest_ref["sha256"])
    if stored != manifest or observed != manifest_ref:
        raise ValueError("LEGACY_RESEARCH_IMMUTABLE_MANIFEST_CHANGED")
    producer = manifest.get("producer_ref")
    canonical = manifest.get("canonical_producer_observation")
    expected_path = (Path(manifest_ref["path"]).resolve().parent / "producer_source.py").resolve()
    if (not isinstance(producer, dict) or set(producer) != {"path", "sha256"}
            or producer not in manifest.get("source_refs", [])
            or Path(producer["path"]).resolve() != expected_path
            or not isinstance(canonical, dict) or set(canonical) != {"path", "sha256"}
            or Path(canonical["path"]).resolve() != Path(extension.__file__).resolve()
            or canonical["sha256"] != producer["sha256"]):
        raise ValueError("LEGACY_RESEARCH_ORIGINAL_PRODUCER_UNBOUND")
    with expected_path.open("rb") as stream:
        data = stream.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024 or hashlib.sha256(data).hexdigest() != producer["sha256"]:
        raise ValueError("LEGACY_RESEARCH_ORIGINAL_PRODUCER_HASH_CHANGED")
    # Frozen dependency identity is required even when this helper is used by
    # a publication guard without a full execution-package object.
    for name, digest in selected.FROZEN_HASHES.items():
        if not any(ref.get("sha256") == digest and Path(ref.get("path", "")).name == Path(name).name
                   for ref in manifest.get("source_refs", [])):
            raise ValueError("LEGACY_RESEARCH_FROZEN_SOURCE_UNBOUND:" + name)
    tree = ast.parse(data.decode("utf-8-sig"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    replay, runner = functions.get("replay_common"), functions.get("run_extension")
    def same(node, code):
        return ast.dump(node, include_attributes=False) == ast.dump(ast.parse(code).body[0], include_attributes=False)
    targets = [] if replay is None else [node for node in replay.body if isinstance(node, ast.FunctionDef) and node.name == "target"]
    branches = [] if len(targets) != 1 else [node for node in targets[0].body if isinstance(node, ast.If)
        and ast.dump(node.test, include_attributes=False) == ast.dump(ast.parse("spec is None", mode="eval").body, include_attributes=False)]
    solve = 'wanted, diagnostic = runtime["optimizer"].solve(group, shares, values, nav, runtime["risk"], spec, signal)'
    raw = 'wanted = {str(ticker): .05 for ticker in group.loc[group.raw_rank.le(20), "ticker"]}'
    names = 'names = panel.loc[panel.signal_date.eq(signal) & panel.raw_rank.le(20), "ticker"]'
    if (runner is None or len(branches) != 1 or len(branches[0].orelse) != 1
            or not same(branches[0].orelse[0], solve) or not branches[0].body
            or not same(branches[0].body[0], raw)
            or any(arg.arg == "policy" for arg in [*runner.args.args, *runner.args.kwonlyargs])
            or not any(isinstance(node, ast.Assign) and same(node, names) for node in ast.walk(runner))
            or not any(isinstance(node, ast.Assign) and same(node, 'runtime = selected._runtime(root)') for node in ast.walk(runner))
            or not any(isinstance(node, ast.Expr) and same(node, 'selected.verify_frozen(root)') for node in ast.walk(runner))):
        raise ValueError("LEGACY_RESEARCH_ORIGINAL_PRODUCER_SEAM_CHANGED")
    calls = [node for node in ast.walk(runner) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == "replay_common"]
    wanted_call = ast.parse('replay_common(replay, name, spec, panel, prices, runtime, pairs)', mode='eval').body
    if len(calls) != 1 or ast.dump(calls[0], include_attributes=False) != ast.dump(wanted_call, include_attributes=False):
        raise ValueError("LEGACY_RESEARCH_ORIGINAL_PRODUCER_SEAM_CHANGED")
    extension.verify_refs([producer, observed])
    return selected.LEGACY_POLICY


def verified_selected_research(package):
    """Validate the same-policy immutable research vintage without loading models."""
    from scripts.research.a2.evaluation.three_strategy_extension import _capture_json, verify_refs
    from scripts.research.a2.portfolio import selected_hgb as selected
    policy = package.get("policy_id", selected.LEGACY_POLICY)
    if policy not in {selected.LEGACY_POLICY, selected.DIRECT_POLICY}:
        raise ValueError("SELECTED_RESEARCH_POLICY_REQUIRED")
    ref = package.get("performance_extension", {}).get("manifest")
    if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"}
            or package.get("source_refs", {}).get("performance_extension/manifest") != ref
            or package.get("source_hashes", {}).get("performance_extension/manifest") != ref["sha256"]):
        raise ValueError("DIRECT_RESEARCH_MANIFEST_BINDING_REQUIRED")
    manifest, captured = _capture_json(ref["path"], ref["sha256"])
    period = manifest.get("performance_period", {})
    if (not "2026-01-01" <= period.get("start", "") <= period.get("end", "") < "2027-01-01"
            or any(not "2026-01-01" <= row.get("signal_date", "") < "2027-01-01"
                   for row in manifest.get("shared_scores_historical", []))):
        raise ValueError("SELECTED_RESEARCH_2026_BOUNDARY_REQUIRED")
    _verify_extension_contract(manifest)
    if (research_policy(manifest, captured) != policy
            or type(manifest.get("model_fit_calls")) is not int
            or manifest.get("cost_one_way") != .0005
            or manifest.get("initial_cash_coordinate") != 1.
            or manifest["performance_period"].get("decision_clock") != "SIGNAL_CLOSE_NEXT_SESSION_OPEN"
            or package.get("performance_period") != manifest["performance_period"]):
        raise ValueError("DIRECT_RESEARCH_CONTRACT_INVALID")
    # Every frozen scorer/risk dependency must be the same byte-qualified source,
    # rather than trusting a policy string or a package's reported fit count.
    source_refs = manifest["source_refs"]
    for name, expected in selected.FROZEN_HASHES.items():
        frozen = package.get("source_refs", {}).get("frozen/" + name)
        if (not frozen or frozen.get("sha256") != expected
                or package.get("source_hashes", {}).get("frozen/" + name) != expected
                or frozen not in source_refs):
            raise ValueError("DIRECT_RESEARCH_FROZEN_SOURCE_UNBOUND:" + name)
    if (type(package.get("model_fit_calls")) is not int or package["model_fit_calls"] != 0
            or package.get("broker_action_allowed") is not False
            or package.get("shared_scores", {}).get("model_sha256") != selected.FROZEN_HASHES["models/hgb_2026092501.joblib"]):
        raise ValueError("DIRECT_RESEARCH_MODEL_IDENTITY_CHANGED")
    verify_refs([captured])
    return manifest, captured


def verified_direct_research(package):
    """Retain the original DIRECT-only interface and its refusal semantics."""
    from scripts.research.a2.portfolio import selected_hgb as selected
    if package.get("policy_id") != selected.DIRECT_POLICY:
        raise ValueError("DIRECT_RESEARCH_POLICY_REQUIRED")
    return verified_selected_research(package)


def _direct_archive_projection(package, day, research_rows, archived, receipt_ref):
    """Only a validated input-repair revision may differ from research UI scores."""
    from scripts.research.a2.evaluation.three_strategy_extension import verify_refs
    if receipt_ref is None:
        raise ValueError("DIRECT_ARCHIVE_REVISION_REQUIRED:" + day)
    manifest, _ = verified_direct_research(package)
    expected = [row for row in manifest["shared_scores_historical"] if row["signal_date"] == day]
    order = lambda rows: sorted(rows, key=lambda row: row["ticker"])
    if not expected or order(expected) != order(research_rows):
        raise ValueError("DIRECT_ARCHIVE_RESEARCH_SCORES_CHANGED:" + day)
    verify_refs([receipt_ref])  # semantic/selection validation is performed by _revision_selection
    return deepcopy(archived)


def verify_direct_research_prefix(previous, manifest):
    """The original research ledger, including unprojected scores, stays exact."""
    import pandas as pd
    from scripts.research.a2.evaluation.three_strategy_extension import _capture_parquet, verify_refs
    refs = list(previous["source_refs"])
    for sid, strategy in previous["strategies"].items():
        refs.extend(strategy["outputs"].values())
        for kind in ("daily", "targets"):
            before = _capture_parquet(strategy["outputs"][kind])
            after = _capture_parquet(manifest["strategies"][sid]["outputs"][kind])
            try:
                pd.testing.assert_frame_equal(before, after.iloc[:len(before)].reset_index(drop=True), check_exact=True)
            except AssertionError as exc:
                raise ValueError("DIRECT_EXECUTED_RESEARCH_PREFIX_CHANGED:" + sid + ":" + kind) from exc
    verify_refs(refs)
    used = {item["signal_date"] for strategy in previous["strategies"].values() for item in strategy["targets"]}
    old = [row for row in previous["shared_scores_historical"] if row["signal_date"] in used]
    new = [row for row in manifest["shared_scores_historical"] if row["signal_date"] in used]
    order = lambda rows: sorted(rows, key=lambda row: (row["signal_date"], row["ticker"]))
    if order(old) != order(new):
        raise ValueError("DIRECT_EXECUTED_RESEARCH_SCORES_CHANGED")


def _accepted_replay_scores(package, manifest, history_root=None, *, manifest_ref=None):
    """An accepted input repair may replace only scores never used by this replay."""
    from scripts.research.a2.evaluation.three_strategy_extension import accepted_snapshots
    from scripts.research.a2.portfolio import selected_hgb as selected
    if (package.get("policy_id", selected.LEGACY_POLICY) == selected.LEGACY_POLICY
            and package.get("performance_extension", {}).get("source_id") == "NEW_PIT_COMPARISON"):
        previous, _ = verified_selected_research(package)
        if research_policy(manifest, manifest_ref) != selected.LEGACY_POLICY:
            raise ValueError("LEGACY_RESEARCH_PRIOR_POLICY_CHANGED")
        verify_direct_research_prefix(previous, manifest)
    rows = deepcopy(manifest["shared_scores_historical"])
    if not any(key.startswith("history/") for key in package.get("source_refs", {})):
        return rows
    if history_root is None:
        from scripts.common.storage_paths import resolve
        history_root = Path(resolve().daily_root) / "A2_selected_hgb/history"
    snapshots, _ = accepted_snapshots(package, history_root, selected)
    # Direct-risk research retains its accepted research input vintage. Current
    # cash-start snapshots can have a later repaired vintage without rewriting
    # an already executed research signal.
    if package.get("policy_id") == selected.DIRECT_POLICY:
        from scripts.research.a2.evaluation.three_strategy_extension import _capture_json
        previous_ref = package["performance_extension"]["manifest"]
        previous, _ = _capture_json(previous_ref["path"], previous_ref["sha256"])
        if previous.get("policy_id") != selected.DIRECT_POLICY:
            raise ValueError("DIRECT_RESEARCH_PRIOR_POLICY_CHANGED")
        verify_direct_research_prefix(previous, manifest)
        ordered = lambda records: sorted(records, key=lambda row: (row["signal_date"], row["ticker"]))
        grouped = {}
        for row in rows:
            grouped.setdefault(row["signal_date"], []).append(row)
        for day, snapshot in snapshots.items():
            if day not in grouped:
                continue
            archived = [{**row, "signal_date": day} for row in snapshot["shared_scores"]["rows"]]
            if ordered(grouped[day]) != ordered(archived):
                _, _, receipt = selected._revision_selection(package, Path(history_root).resolve(), day)
                grouped[day] = _direct_archive_projection(package, day, grouped[day], archived, receipt)
        return [row for day in sorted(grouped) for row in grouped[day]]
    used = {item["signal_date"] for strategy in manifest["strategies"].values()
            for item in strategy["targets"]}
    grouped = {}
    for row in rows:
        grouped.setdefault(row["signal_date"], []).append(row)
    for day, snapshot in snapshots.items():
        if day not in grouped:
            continue
        accepted = [{**row, "signal_date": day} for row in snapshot["shared_scores"]["rows"]]
        old = sorted(grouped[day], key=lambda row: row["ticker"])
        new = sorted(accepted, key=lambda row: row["ticker"])
        if json.dumps(old, sort_keys=True, allow_nan=False) == json.dumps(new, sort_keys=True, allow_nan=False):
            continue
        _, _, receipt = selected._revision_selection(package, Path(history_root).resolve(), day)
        if day in used or day < manifest["performance_period"]["end"] or receipt is None:
            raise ValueError("EXECUTED_OR_UNAUTHORIZED_SHARED_SCORE_CHANGED:" + day)
        grouped[day] = accepted
    return [row for day in sorted(grouped) for row in grouped[day]]


def _verify_extension_contract(manifest):
    from scripts.research.a2.evaluation.three_strategy_extension import verify_refs
    period = manifest["performance_period"]
    if (manifest.get("source_id") != "NEW_PIT_COMPARISON"
            or manifest.get("model_fit_calls") != 0
            or manifest.get("broker_action_allowed") is not False
            or period.get("price_basis") != "PIT_FORWARD_REHAB_INDEX"
            or set(manifest["strategies"]) != {"RAW_A2", "HGB_DIAG_5", "HGB_FACTOR_5"}):
        raise ValueError("EXTENSION_CONTRACT_INVALID")
    refs = list(manifest["source_refs"])
    for item in manifest["strategies"].values():
        refs.extend(item["outputs"].values())
        days = [row["date"] for row in item["daily"]]
        if not days or days[0] != period["start"] or days[-1] != period["end"] or len(days) != period["days"]:
            raise ValueError("EXTENSION_CALENDAR_INVALID")
    if any([row["date"] for row in item["daily"]] !=
           [row["date"] for row in manifest["strategies"]["RAW_A2"]["daily"]]
           for item in manifest["strategies"].values()):
        raise ValueError("EXTENSION_COMMON_CALENDAR_CHANGED")
    verify_refs(refs)


def merge_extension(package, manifest, manifest_path, *, history_root=None):
    from scripts.research.a2.evaluation.three_strategy_extension import _capture_json, verify_refs
    manifest_path = Path(manifest_path)
    stored, manifest_ref = _capture_json(manifest_path)
    if stored != manifest:
        raise ValueError("EXTENSION_MANIFEST_CONTENT_CHANGED")
    _verify_extension_contract(manifest)
    period = manifest["performance_period"]
    merged = deepcopy(package)
    merged["performance_period"] = deepcopy(period)
    for sid in merged["strategies"]:
        for key in ("daily", "targets", "summary"):
            merged["strategies"][sid][key] = deepcopy(manifest["strategies"][sid][key])
    merged["raw_reference"] = {key: deepcopy(manifest["strategies"]["RAW_A2"][key])
                               for key in ("label", "daily", "targets", "summary")}
    merged["raw_reference"].update(strategy_id="RAW_A2", performance_period=deepcopy(period))
    merged["shared_scores"]["historical"] = _accepted_replay_scores(package, manifest, history_root, manifest_ref=manifest_ref)
    verify_refs([manifest_ref])
    merged["performance_extension"] = {key: deepcopy(manifest[key]) for key in (
        "source_id", "status", "performance_period", "requested_end_date", "blocked_next",
        "model_fit_calls", "broker_action_allowed", "cost_one_way", "initial_cash_coordinate")}
    for key in ("signal_end_date", "execution_open"):
        if key in manifest:
            merged["performance_extension"][key] = deepcopy(manifest[key])
    merged["performance_extension"]["manifest"] = manifest_ref
    # Keep the original frozen evidence, bind the new full-period comparison separately.
    merged.setdefault("source_refs", {})["performance_extension/manifest"] = manifest_ref
    merged.setdefault("source_hashes", {})["performance_extension/manifest"] = manifest_ref["sha256"]
    merged["limitations"] = list(manifest["limitations"]) + [
        "PIT adjusted-price share/cash coordinates; not a broker corporate-action account ledger."]
    merged["generated_at"] = datetime.now(timezone.utc).isoformat()
    return merged


def refresh_selected_performance(paths, package, current_report_path, output_path, progress=None, *, held_price_reuse=None, execution_open_manifest=None, execution_end=None, snapshot_repair=None):
    """Advance the accepted legacy vintage through the existing replay owner."""
    from scripts.research.a2.evaluation.three_strategy_extension import capture_full_prices, bound_selected_research
    from scripts.research.a2.portfolio import selected_hgb as selected
    policy, active_output = selected.active_policy(paths)
    output_path = Path(output_path).resolve()
    if (policy != selected.LEGACY_POLICY or package.get("policy_id", selected.LEGACY_POLICY) != policy
            or output_path != Path(active_output).resolve()):
        raise ValueError("LEGACY_DAILY_ACTIVE_POLICY_OR_OUTPUT_CHANGED")
    report = json.loads(Path(current_report_path).read_text(encoding="utf-8"))
    target = selected._date(report["data_date"])
    from scripts import daily_recommendation_inputs as calendar_inputs
    calendar = calendar_inputs.latest_completed_session(
        calendar_inputs.load_frozen_binding(paths.repo_root), datetime.now(timezone.utc))
    if (report.get("status") != "READY" or not "2026-01-01" <= target < "2027-01-01"
            or target not in calendar["sessions"] or target > calendar["target_date"]):
        raise ValueError("LEGACY_DAILY_COMPLETED_SIGNAL_REQUIRED")
    prior_ref = None
    current = package
    if output_path.is_file():
        from apps.demo_console.adapters.selected_strategies_reader import validate_package
        from scripts.research.a2.evaluation.three_strategy_extension import _capture_json, verify_refs
        previous, observation = _capture_json(output_path)
        validate_package(previous)
        if previous.get("policy_id", selected.LEGACY_POLICY) != policy:
            raise ValueError("LEGACY_DAILY_PRIOR_POLICY_CHANGED")
        if previous.get("performance_extension", {}).get("source_id") == "NEW_PIT_COMPARISON":
            _, prior, prior_ref, _ = bound_selected_research(paths)
            current = merge_extension(package, prior, prior_ref["path"], history_root=output_path.parent / "history")
            verify_refs([observation])
            if prior['performance_period']['end'] > target:
                from scripts.research.a2.evaluation.demo_performance_prices import execution_open_clock
                phase = prior.get('execution_open', {})
                if (phase.get('signal_end_date') != target
                        or phase.get('execution_end_date') != prior['performance_period']['end']
                        or phase.get('consumer_fields') != ['open']
                        or phase.get('terminal_close_available') is not False
                        or phase.get('model_feature_eligibility_granted') is not False
                        or phase.get('manifest') not in prior['source_refs']):
                    raise ValueError('LEGACY_DAILY_FUTURE_EXECUTION_UNBOUND')
                observed_at = datetime.fromisoformat(phase['as_of_utc'].replace('Z','+00:00'))
                if observed_at.tzinfo is None or observed_at > datetime.now(timezone.utc):
                    raise ValueError('LEGACY_DAILY_FUTURE_EXECUTION_UNBOUND')
                execution_open_clock(target, prior['performance_period']['end'], calendar['sessions'], phase['as_of_utc'])
            # Preserve a qualified opening overlay ahead of the latest close too.
            # Only the current signal changes; there is no new execution to append.
            if (execution_open_manifest is None and execution_end is None
                    and prior['status'] == 'READY' and prior.get('blocked_next') is None
                    and prior['performance_period']['end'] >= target):
                if progress:
                    progress("复用已验证旧 HGB 同执行日研究账本；仅更新当前收盘目标。")
                selected.publish(current, output_path, **({"snapshot_repair": snapshot_repair} if snapshot_repair is not None else {}))
                return current
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_") + uuid.uuid4().hex[:8]
    root = Path(paths.daily_root) / "A2_selected_hgb/research_runs" / run_id
    if progress:
        progress("同步三策略共同研究区间：保留已接受价格与评分，再追加合格执行日。")
    open_args = ({"execution_open_manifest": execution_open_manifest, "execution_end": execution_end}
                 if execution_open_manifest is not None or execution_end is not None else {})
    prior_args = ({"prior_research_manifest": prior_ref} if prior_ref is not None else {})
    prices, inputs = capture_full_prices(root / "inputs", repo_root=paths.repo_root,
        current_report_path=current_report_path, **open_args, **prior_args)
    manifest, manifest_path = replay_with_held_updates(paths, root, prices, inputs, target, progress,
        policy=policy, **open_args, **prior_args,
        **({"held_price_reuse": held_price_reuse} if held_price_reuse is not None else {}))
    merged = merge_extension(current, manifest, manifest_path, history_root=output_path.parent / "history")
    selected.publish(merged, output_path, **({"snapshot_repair": snapshot_repair} if snapshot_repair is not None else {}))
    return merged


def replay_with_held_updates(paths, root, prices, inputs, target, progress=None, *, held_price_reuse=None, policy=None, execution_open_manifest=None, execution_end=None, prior_research_manifest=None):
    """Refresh retired held names through the same native-source qualification gates."""
    from scripts.research.a2.evaluation.three_strategy_extension import run_extension, supplement_held_prices
    attempted = set()
    for attempt in range(8):
        output = Path(root) / ("replay" if attempt == 0 else "replay_" + str(attempt))
        manifest = run_extension(prices, inputs, output, repo_root=paths.repo_root, target_date=target,
            **({"policy": policy} if policy is not None else {}),
            **({"prior_research_manifest": prior_research_manifest} if prior_research_manifest is not None else {}),
            **({"execution_open_manifest": execution_open_manifest, "execution_end": execution_end}
               if execution_open_manifest is not None or execution_end is not None else {}))
        gap = manifest.get("blocked_next") or {}
        # An open-only phase never silently starts closed-day history acquisition.
        if execution_open_manifest is not None and gap.get("execution_date") == execution_end:
            break
        if gap.get("reason") != "HELD_EXECUTION_PRICE_MISSING":
            break
        tickers = sorted({ticker for _, ticker in gap.get("keys", [])} - attempted)
        if not tickers or attempt == 7:
            break
        attempted.update(tickers)
        if progress:
            progress("补查已退出当日股票池的历史持仓价格：" + ", ".join(tickers))
        try:
            prices, inputs = supplement_held_prices(prices, inputs,
                Path(root) / ("held_inputs_" + str(attempt)), tickers, target=target, repo_root=paths.repo_root,
                **({"reuse_sources": held_price_reuse} if held_price_reuse is not None else {}))
        except Exception as exc:
            if progress:
                progress("历史持仓尾段价格尚未通过资格检查；保留实际回放截止日：" + str(exc))
            break
    return manifest, output / "manifest.json"


def publish_current_preserving_replay(package, output_path, *, paths=None, snapshot_repair=None):
    """Preserve qualified charts; identical same-day execution bytes stay immutable."""
    from scripts.research.a2.portfolio import selected_hgb as selected
    previous_path = Path(output_path)
    if snapshot_repair is not None and paths is None:
        raise ValueError("LEGACY_FALLBACK_REPAIR_REQUIRES_BOUND_PATHS")
    merged = deepcopy(package)
    if paths is not None:
        policy, active_output = selected.active_policy(paths)
        if (policy != selected.LEGACY_POLICY
                or package.get("policy_id", selected.LEGACY_POLICY) != policy
                or previous_path.resolve() != Path(active_output).resolve()):
            raise ValueError("LEGACY_FALLBACK_ACTIVE_POLICY_OR_OUTPUT_CHANGED")
    if previous_path.is_file():
        previous = json.loads(previous_path.read_text(encoding="utf-8"))
        observation = None
        if paths is not None:
            from scripts.research.a2.evaluation.three_strategy_extension import (
                _capture_json, bound_selected_research, verify_refs)
            _, observation = _capture_json(previous_path)
            previous, manifest, manifest_ref, bound_observation = bound_selected_research(paths)
            if (bound_observation != observation
                    or Path(previous["package_path"]).resolve() != previous_path.resolve()
                    or previous["package_sha256"] != observation["sha256"]
                    or previous.get("policy_id", selected.LEGACY_POLICY) != policy):
                raise ValueError("LEGACY_FALLBACK_CANONICAL_OBSERVATION_CHANGED")
            import hashlib
            origin = hashlib.sha256(json.dumps(package, sort_keys=True, allow_nan=False).encode()).hexdigest()
            current_snapshot = selected._capture_snapshot(package, origin)
            prior_snapshot = selected._capture_snapshot(previous, observation["sha256"])
            current_day, prior_day = current_snapshot["signal_date"], prior_snapshot["signal_date"]
            if current_day < prior_day:
                raise ValueError("LEGACY_FALLBACK_SIGNAL_REGRESSED")
            if current_day == prior_day:
                # Unchanged live execution identity remains a byte-preserving NOOP.
                unchanged = (selected._same_snapshot_decision(current_snapshot, prior_snapshot)
                    and current_snapshot["source_refs"] == prior_snapshot["source_refs"]
                    and current_snapshot["source_hashes"] == prior_snapshot["source_hashes"]
                    and package["shared_scores"]["current"] == previous["shared_scores"]["current"]
                    and all(package["strategies"][sid]["application"]
                            == previous["strategies"][sid]["application"] for sid in selected.STRATEGY_IDS))
                if unchanged:
                    verify_refs([observation])
                    return deepcopy(previous)
                if snapshot_repair is None:
                    raise ValueError("LEGACY_FALLBACK_SAME_SIGNAL_DECISION_OR_INPUT_CHANGED")
                # Only the original, source-bound offline-repair contract can
                # authorize a same-day candidate revision. Publication below
                # retains the original archive and binds its revision receipt.
                selected._validate_input_repair(current_snapshot, prior_snapshot, snapshot_repair)
        if previous.get("performance_extension", {}).get("source_id") == "NEW_PIT_COMPARISON":
            from scripts.research.a2.evaluation.three_strategy_extension import verify_refs
            verify_refs([previous["performance_extension"]["manifest"]])
            manifest_ref = previous["performance_extension"]["manifest"]
            manifest = json.loads(Path(manifest_ref["path"]).read_text(encoding="utf-8"))
            merged = merge_extension(package, manifest, manifest_ref["path"],
                                     history_root=previous_path.parent / "history")
            for name, ref in previous["source_refs"].items():
                if ref == manifest_ref:
                    merged["source_refs"][name] = deepcopy(ref)
                    merged["source_hashes"][name] = ref["sha256"]
        if observation is not None:
            verify_refs([observation])
    selected.publish(merged, output_path, **({"snapshot_repair": snapshot_repair} if snapshot_repair is not None else {}))
    return merged


def publish_display_performance(paths, package_path, manifest_path):
    """Publish the existing base-bound display reference, never execution bytes."""
    import hashlib
    import pandas as pd
    from scripts.common.storage_paths import assert_safe_output_path
    from scripts.research.a2.evaluation import three_strategy_extension as extension
    source, target = Path(package_path).resolve(), Path(manifest_path).resolve()
    if not target.is_relative_to(paths.backtest_root.resolve()):
        raise ValueError("DISPLAY_MANIFEST_OUTSIDE_BACKTEST")
    original = source.read_bytes()
    base = json.loads(original.decode("utf-8-sig"))
    manifest, manifest_ref = extension._capture_json(target)
    from scripts.research.a2.portfolio import selected_hgb as selected
    if research_policy(manifest, manifest_ref) != base.get("policy_id", selected.LEGACY_POLICY):
        raise ValueError("DISPLAY_POLICY_CHANGED")
    merged = merge_extension(base, manifest, target, history_root=source.parent / "history")
    if (merged["shared_scores"].get("current") != base["shared_scores"].get("current")
            or any(merged["strategies"][sid][key] != base["strategies"][sid].get(key)
                   for sid in base["strategies"] for key in ("application", "application_history")
                   if key in base["strategies"][sid])):
        raise ValueError("DISPLAY_EXECUTION_TARGET_CHANGED")
    previous = base["performance_extension"]["manifest"]
    overlay = source.parent / "performance_reference.json"
    if overlay.exists():
        observed = json.loads(overlay.read_text(encoding="utf-8-sig"))
        if observed.get("base_package_sha256") == hashlib.sha256(original).hexdigest():
            previous = observed["performance_manifest"]
    old, _ = extension._capture_json(previous["path"], previous["sha256"])
    if manifest["performance_period"]["end"] < old["performance_period"]["end"]:
        raise ValueError("DISPLAY_VERIFIED_CUTOFF_REGRESSED")
    for sid in old["strategies"]:
        for kind in ("daily", "targets"):
            before_ref = old["strategies"][sid]["outputs"][kind]
            after_ref = manifest["strategies"][sid]["outputs"][kind]
            before = extension._capture_parquet(before_ref)
            after = extension._capture_parquet(after_ref)
            try:
                pd.testing.assert_frame_equal(before, after.iloc[:len(before)].reset_index(drop=True),
                                              check_exact=True)
            except AssertionError as exc:
                raise ValueError("DISPLAY_VERIFIED_PREFIX_CHANGED:" + sid + ":" + kind) from exc
    old_scores = old["shared_scores_historical"]
    prior_days = {row["signal_date"] for row in old_scores}
    retained = [row for row in manifest["shared_scores_historical"] if row["signal_date"] in prior_days]
    order = lambda rows: sorted(rows, key=lambda row: (row["signal_date"], row["ticker"]))
    if order(retained) != order(old_scores):
        raise ValueError("DISPLAY_VERIFIED_SCORES_CHANGED")
    reference = {"schema": "HGB_DISPLAY_PERFORMANCE_REFERENCE_V1", "policy_id": base["policy_id"],
        "base_package_sha256": hashlib.sha256(original).hexdigest(), "performance_manifest": manifest_ref}
    assert_safe_output_path(overlay, paths=paths, kind="daily")
    if source.read_bytes() != original:
        raise ValueError("DISPLAY_BASE_CHANGED_DURING_REFRESH")
    from scripts.common.daily_support import save
    save(overlay, reference)
    if source.read_bytes() != original:
        raise ValueError("DISPLAY_BASE_CHANGED_DURING_PUBLICATION")
    return reference
