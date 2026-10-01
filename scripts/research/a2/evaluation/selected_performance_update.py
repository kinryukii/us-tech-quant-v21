"""Publish one verified common replay window alongside current selected targets."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import json
import uuid


def merge_extension(package, manifest, manifest_path):
    from scripts.research.a2.evaluation.three_strategy_extension import reference, verify_refs
    manifest_path = Path(manifest_path)
    stored = json.loads(manifest_path.read_text(encoding="utf-8"))
    if stored != manifest:
        raise ValueError("EXTENSION_MANIFEST_CONTENT_CHANGED")
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
    merged = deepcopy(package)
    merged["performance_period"] = deepcopy(period)
    for sid in merged["strategies"]:
        for key in ("daily", "targets", "summary"):
            merged["strategies"][sid][key] = deepcopy(manifest["strategies"][sid][key])
    merged["raw_reference"] = {key: deepcopy(manifest["strategies"]["RAW_A2"][key])
                               for key in ("label", "daily", "targets", "summary")}
    merged["raw_reference"].update(strategy_id="RAW_A2", performance_period=deepcopy(period))
    merged["shared_scores"]["historical"] = deepcopy(manifest["shared_scores_historical"])
    manifest_ref = reference(manifest_path)
    merged["performance_extension"] = {key: deepcopy(manifest[key]) for key in (
        "source_id", "status", "performance_period", "requested_end_date", "blocked_next",
        "model_fit_calls", "broker_action_allowed", "cost_one_way", "initial_cash_coordinate")}
    merged["performance_extension"]["manifest"] = manifest_ref
    # Keep the original frozen evidence, bind the new full-period comparison separately.
    merged.setdefault("source_refs", {})["performance_extension/manifest"] = manifest_ref
    merged.setdefault("source_hashes", {})["performance_extension/manifest"] = manifest_ref["sha256"]
    merged["limitations"] = list(manifest["limitations"]) + [
        "PIT adjusted-price share/cash coordinates; not a broker corporate-action account ledger."]
    merged["generated_at"] = datetime.now(timezone.utc).isoformat()
    return merged


def refresh_selected_performance(paths, package, current_report_path, output_path, progress=None, *, held_price_reuse=None):
    from scripts.research.a2.evaluation.three_strategy_extension import capture_full_prices
    from scripts.research.a2.portfolio.selected_hgb import publish
    report = json.loads(Path(current_report_path).read_text(encoding="utf-8"))
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_") + uuid.uuid4().hex[:8]
    root = Path(paths.daily_root) / "A2_selected_hgb/research_runs" / run_id
    if progress:
        progress("同步三策略共同研究区间：校验全部候选、历史持仓价格与企业行动，再更新图表。")
    prices, inputs = capture_full_prices(root / "inputs", repo_root=paths.repo_root,
                                        current_report_path=current_report_path)
    manifest, manifest_path = replay_with_held_updates(paths, root, prices, inputs, report["data_date"], progress,
        **({"held_price_reuse": held_price_reuse} if held_price_reuse is not None else {}))
    merged = merge_extension(package, manifest, manifest_path)
    publish(merged, output_path)
    return merged


def replay_with_held_updates(paths, root, prices, inputs, target, progress=None, *, held_price_reuse=None):
    """Refresh retired held names through the same native-source qualification gates."""
    from scripts.research.a2.evaluation.three_strategy_extension import run_extension, supplement_held_prices
    attempted = set()
    for attempt in range(8):
        output = Path(root) / ("replay" if attempt == 0 else "replay_" + str(attempt))
        manifest = run_extension(prices, inputs, output, repo_root=paths.repo_root, target_date=target)
        gap = manifest.get("blocked_next") or {}
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


def publish_current_preserving_replay(package, output_path):
    """A replay failure must not retract previously verified charts or current targets."""
    from scripts.research.a2.portfolio.selected_hgb import publish
    previous_path = Path(output_path)
    merged = deepcopy(package)
    if previous_path.is_file():
        previous = json.loads(previous_path.read_text(encoding="utf-8"))
        if previous.get("performance_extension", {}).get("source_id") == "NEW_PIT_COMPARISON":
            from scripts.research.a2.evaluation.three_strategy_extension import verify_refs
            verify_refs([previous["performance_extension"]["manifest"]])
            merged["performance_period"] = deepcopy(previous["performance_period"])
            merged["raw_reference"] = deepcopy(previous["raw_reference"])
            merged["performance_extension"] = deepcopy(previous["performance_extension"])
            merged["shared_scores"]["historical"] = deepcopy(previous["shared_scores"]["historical"])
            for sid in merged["strategies"]:
                for key in ("daily", "targets", "summary"):
                    merged["strategies"][sid][key] = deepcopy(previous["strategies"][sid][key])
            for name, ref in previous["source_refs"].items():
                if ref == previous["performance_extension"]["manifest"]:
                    merged["source_refs"][name] = deepcopy(ref)
                    merged["source_hashes"][name] = ref["sha256"]
            merged["limitations"] = deepcopy(previous["limitations"])
    publish(merged, output_path)
    return merged
