from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "outputs" / "v20" / "ops"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

V20_7_READ_FIRST = ROOT / "outputs" / "v20" / "ops" / "V20_7_READ_FIRST.txt"
V20_7_VALIDATION = ROOT / "outputs" / "v20" / "consolidation" / "V20_7_VALIDATION_SUMMARY.csv"
V20_7_SOURCE_GATE = ROOT / "outputs" / "v20" / "consolidation" / "V20_7_SOURCE_GATE_DECISION.csv"
V20_7_NORMALIZED_GATE = ROOT / "outputs" / "v20" / "consolidation" / "V20_7_NORMALIZED_DATA_READINESS_GATE.csv"
V20_7_STALE_DATA = ROOT / "outputs" / "v20" / "consolidation" / "V20_7_STALE_DATA_AUDIT.csv"
V20_7_LEAKAGE = ROOT / "outputs" / "v20" / "consolidation" / "V20_7_LEAKAGE_RISK_AUDIT.csv"
V20_7_PIT = ROOT / "outputs" / "v20" / "consolidation" / "V20_7_POINT_IN_TIME_AVAILABILITY_AUDIT.csv"
V20_7_DATE_COVERAGE = ROOT / "outputs" / "v20" / "consolidation" / "V20_7_DATE_FIELD_COVERAGE_AUDIT.csv"
V20_7_OUTCOME_READY = ROOT / "outputs" / "v20" / "consolidation" / "V20_7_OUTCOME_WINDOW_READINESS_AUDIT.csv"
V20_7_BENCHMARK_READY = ROOT / "outputs" / "v20" / "consolidation" / "V20_7_BENCHMARK_WINDOW_READINESS_AUDIT.csv"
V20_7_SAMPLE_READY = ROOT / "outputs" / "v20" / "consolidation" / "V20_7_SAMPLE_METADATA_READINESS_AUDIT.csv"
V20_7_BLOCKERS = ROOT / "outputs" / "v20" / "consolidation" / "V20_7_STALE_LEAKAGE_PIT_BLOCKER_REGISTER.csv"
V20_7_NEXT_REQ = ROOT / "outputs" / "v20" / "consolidation" / "V20_7_NEXT_NORMALIZED_DATA_REQUIREMENTS.csv"

V20_5_SOURCE_REGISTRY = ROOT / "outputs" / "v20" / "consolidation" / "V20_5_SOURCE_ARTIFACT_REGISTRY.csv"
V20_6_SOURCE_HASH = ROOT / "outputs" / "v20" / "consolidation" / "V20_6_SOURCE_HASH_LEDGER.csv"
V20_6_INPUT_HASH = ROOT / "outputs" / "v20" / "consolidation" / "V20_6_INPUT_HASH_LEDGER.csv"
V20_6_VERSION_BINDING = ROOT / "outputs" / "v20" / "consolidation" / "V20_6_VERSION_BINDING_LEDGER.csv"
V20_6_HASH_RUN_ID_PAIRING = ROOT / "outputs" / "v20" / "consolidation" / "V20_6_HASH_RUN_ID_PAIRING.csv"
V20_6_READ_FIRST = ROOT / "outputs" / "v20" / "ops" / "V20_6_READ_FIRST.txt"

OUT_BLOCKER_INVENTORY = CONSOLIDATION / "V20_7R_NORMALIZED_DATA_BLOCKER_INVENTORY.csv"
OUT_ACTIVE_SOURCE_MAP = CONSOLIDATION / "V20_7R_ACTIVE_MARKET_SOURCE_CANDIDATE_MAP.csv"
OUT_FIELD_CONTRACT = CONSOLIDATION / "V20_7R_REQUIRED_MARKET_DATA_FIELD_CONTRACT.csv"
OUT_PIT_PLAN = CONSOLIDATION / "V20_7R_PIT_FIELD_REQUIREMENT_PLAN.csv"
OUT_FRESHNESS_PLAN = CONSOLIDATION / "V20_7R_FRESHNESS_RULE_REQUIREMENT_PLAN.csv"
OUT_LEAKAGE_PLAN = CONSOLIDATION / "V20_7R_LEAKAGE_CONTROL_REQUIREMENT_PLAN.csv"
OUT_SAMPLE_PLAN = CONSOLIDATION / "V20_7R_SAMPLE_METADATA_REQUIREMENT_PLAN.csv"
OUT_ENTRY_REQ = CONSOLIDATION / "V20_7R_V20_8_ENTRY_REQUIREMENTS.csv"
OUT_SEQUENCE = CONSOLIDATION / "V20_7R_RESOLUTION_SEQUENCE.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_7R_VALIDATION_SUMMARY.csv"

REPORT = READ_CENTER / "V20_7R_NORMALIZED_DATA_BLOCKER_RESOLUTION_PLAN_REPORT.md"
ALIAS = READ_CENTER / "V20_CURRENT_NORMALIZED_DATA_BLOCKER_STATUS.md"
READ_FIRST = OPS / "V20_7R_READ_FIRST.txt"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def read_kv(text: str | None) -> dict[str, str]:
    data: dict[str, str] = {}
    if not text:
        return data
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            return list(csv.DictReader(fh))
    except Exception:
        return []


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def build_dependency_state() -> dict[str, str]:
    rf = read_kv(read_text(V20_7_READ_FIRST))
    val_rows = read_csv(V20_7_VALIDATION)
    val = val_rows[0] if val_rows else {}
    dep_ok = (
        rf.get("STALE_LEAKAGE_PIT_GATE_EXECUTED") == "TRUE"
        and rf.get("READY_FOR_NORMALIZED_RESEARCH_DATASET_NEXT") == "FALSE"
        and val.get("stale_leakage_pit_gate_executed") == "TRUE"
        and val.get("ready_for_normalized_research_dataset_next") == "FALSE"
    )
    return {
        "rf": rf,
        "dep_ok": tf(dep_ok),
        "source_gate_status": read_csv(V20_7_SOURCE_GATE)[0].get("gate_status", "BLOCKED") if read_csv(V20_7_SOURCE_GATE) else "BLOCKED",
        "normalized_ready": read_csv(V20_7_NORMALIZED_GATE)[0].get("allowed_for_v20_8_normalized_research_dataset", "FALSE") if read_csv(V20_7_NORMALIZED_GATE) else "FALSE",
    }


def source_registry_rows() -> list[dict[str, str]]:
    return read_csv(V20_5_SOURCE_REGISTRY)


def source_hash_rows() -> list[dict[str, str]]:
    return read_csv(V20_6_SOURCE_HASH)


def input_hash_rows() -> list[dict[str, str]]:
    return read_csv(V20_6_INPUT_HASH)


def version_binding_rows() -> list[dict[str, str]]:
    return read_csv(V20_6_VERSION_BINDING)


def pairing_rows() -> list[dict[str, str]]:
    return read_csv(V20_6_HASH_RUN_ID_PAIRING)


def source_hash_by_id() -> dict[str, dict[str, str]]:
    return {row.get("source_artifact_id", ""): row for row in source_hash_rows()}


def input_hash_by_id() -> dict[str, dict[str, str]]:
    return {row.get("source_artifact_id", ""): row for row in input_hash_rows()}


def build_blocker_inventory(v207_blockers: list[dict[str, str]], normalized_ready: bool) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for idx, row in enumerate(v207_blockers, start=1):
        rows.append(
            {
                "inventory_id": f"INV-{idx:02d}",
                "blocker_id": row.get("blocker_id", ""),
                "blocker_category": row.get("blocker_category", ""),
                "blocked_layer": row.get("affected_future_layer", ""),
                "blocker_description": row.get("blocker_description", ""),
                "current_status": row.get("current_status", "BLOCKED"),
                "source_of_truth": "V20_7_STALE_LEAKAGE_PIT_BLOCKER_REGISTER",
                "resolution_needed_before": row.get("required_resolution_before", "V20.8_NORMALIZED_RESEARCH_DATASET"),
                "v20_8_impact": "BLOCKS_V20_8" if not normalized_ready else "RESOLVED_FOR_V20_8",
                "plan_status": "OPEN",
            }
        )

    plan_blockers = [
        ("INV-13", "NO_ACTIVE_PIT_SOURCE_CERTIFICATION", "active market source certification", "Active runtime architecture/report sources do not provide PIT-ready market data.", "V20.8_NORMALIZED_RESEARCH_DATASET", "BLOCKS_V20_8"),
        ("INV-14", "SEALED_BASELINE_ONLY", "baseline comparison isolation", "V18/V19 candidate/price files remain historical reference only.", "V20.8_NORMALIZED_RESEARCH_DATASET", "BLOCKS_V20_8"),
        ("INV-15", "NO_SAMPLE_ID_CONTRACT", "sample metadata", "sample_id design, hash linkage, and active flag rules are not yet certified for V20.8.", "V20.8_NORMALIZED_RESEARCH_DATASET", "BLOCKS_V20_8"),
        ("INV-16", "NO_SIGNAL_OUTCOME_BOUNDARY", "signal/outcome separation", "signal-side fields and outcome-side fields are still only planning concepts.", "V20.8_NORMALIZED_RESEARCH_DATASET", "BLOCKS_V20_8"),
        ("INV-17", "NO_ACTIVE_FRESHNESS_RULE", "freshness rule certification", "active market-source freshness windows are not certified.", "V20.8_NORMALIZED_RESEARCH_DATASET", "BLOCKS_V20_8"),
        ("INV-18", "NO_ACTIVE_LEAKAGE_CONTROL", "leakage control certification", "realized future returns, benchmark future returns, and post-event labels remain blocked from signal-side use.", "V20.8_NORMALIZED_RESEARCH_DATASET", "BLOCKS_V20_8"),
    ]
    for blocker_id, category, layer, desc, needed, impact in plan_blockers:
        rows.append(
            {
                "inventory_id": blocker_id,
                "blocker_id": category,
                "blocker_category": category,
                "blocked_layer": layer,
                "blocker_description": desc,
                "current_status": "PLANNING_BLOCKED",
                "source_of_truth": "V20_7R_PLAN",
                "resolution_needed_before": needed,
                "v20_8_impact": impact,
                "plan_status": "OPEN",
            }
        )
    return rows


def candidate_category_label(category: str) -> str:
    return {
        "current_candidate_outputs": "candidate_snapshot",
        "current_ranked_candidate_outputs": "ranked_candidate_snapshot",
        "current_top_candidate_outputs": "top_candidate_snapshot",
        "price_data_outputs": "price_overlay_snapshot",
    }.get(category, "unknown")


def build_active_market_source_candidate_map(registry_rows: list[dict[str, str]]) -> list[dict[str, object]]:
    hashes = source_hash_by_id()
    rows: list[dict[str, object]] = []
    for row in registry_rows:
        category = row.get("source_category", "")
        if category not in {
            "current_candidate_outputs",
            "current_ranked_candidate_outputs",
            "current_top_candidate_outputs",
            "price_data_outputs",
        }:
            continue
        sh = hashes.get(row.get("source_artifact_id", ""), {})
        rows.append(
            {
                "candidate_id": f"CAND-{row.get('source_artifact_id', '')}",
                "source_artifact_id": row.get("source_artifact_id", ""),
                "source_name": row.get("source_name", ""),
                "source_category": category,
                "candidate_classification": candidate_category_label(category),
                "canonical_path": row.get("canonical_path", ""),
                "source_status": row.get("source_status", ""),
                "sealed_baseline": row.get("sealed_baseline", ""),
                "current_runtime_source": row.get("current_runtime_source", ""),
                "hash_status": sh.get("hash_status", "MISSING"),
                "source_hash": sh.get("source_hash", "MISSING"),
                "historical_reference_flag": "TRUE",
                "active_runtime_flag": "FALSE",
                "pit_ready_now": "FALSE",
                "freshness_ready_now": "FALSE",
                "leakage_ready_now": "FALSE",
                "usable_for_v20_8": "FALSE",
                "blocker_reason": "Sealed historical baseline comparison source only; active PIT-ready certification is still absent.",
            }
        )
    return rows


def build_required_market_field_contract() -> list[dict[str, object]]:
    rows = [
        ("F01", "ticker", "entity identifier", "all active market sources", "required", "BLOCKED", "Ticker-level linkage is required before normalization."),
        ("F02", "observation_date", "signal-side date", "candidate / ranked / top candidate sources", "required", "BLOCKED", "Observation date is needed for PIT-aligned signal construction."),
        ("F03", "signal_date", "signal-side date alias", "candidate / ranked / top candidate sources", "required_if_observation_missing", "BLOCKED", "Signal-date alias may be used only as a controlled fallback."),
        ("F04", "price_date", "market-price date", "price_data_outputs", "required", "BLOCKED", "Price-date lineage is required for the price source."),
        ("F05", "latest_price_date", "market-price date alias", "price_data_outputs", "required_if_price_date_missing", "BLOCKED", "Latest-price-date may be used only when explicitly mapped."),
        ("F06", "availability_date", "publication / availability date", "all active market sources", "required", "BLOCKED", "Availability date is required for PIT gating."),
        ("F07", "run_timestamp", "fallback availability timestamp", "all active market sources", "required_if_availability_missing", "BLOCKED", "Run timestamp is the fallback only if availability date is unavailable."),
        ("F08", "source_hash", "lineage binding field", "all active market sources", "required", "BLOCKED", "Source hash linkage is required before V20.8."),
        ("F09", "run_id", "lineage binding field", "all active market sources", "required", "BLOCKED", "Run ID linkage is required before V20.8."),
        ("F10", "sample_id", "sample identity field", "normalized research dataset", "required", "BLOCKED", "Sample ID design is required before any normalized dataset can be created."),
        ("F11", "signal_side_fields", "signal/outcome separation", "normalized research dataset", "required", "BLOCKED", "Signal-side fields must exclude realized future returns."),
        ("F12", "outcome_side_fields", "signal/outcome separation", "normalized outcome dataset", "required", "BLOCKED", "Outcome-side fields must remain isolated to the outcome layer."),
    ]
    return [
        {
            "contract_id": row[0],
            "field_name": row[1],
            "field_role": row[2],
            "required_for_source_category": row[3],
            "required_now": row[4],
            "required_before_v20_8": "TRUE",
            "current_status": row[5],
            "blocker_reason": row[6],
        }
        for row in rows
    ]


def build_pit_field_plan() -> list[dict[str, object]]:
    rows = [
        ("PIT-01", "observation_date", "signal observation", "candidate/ranked/top candidate outputs", "REQUIRED", "BLOCKED", "Needed for point-in-time alignment of signal construction."),
        ("PIT-02", "availability_date", "availability/publication", "all active market sources", "REQUIRED", "BLOCKED", "Needed to ensure data was available before use."),
        ("PIT-03", "publication_date", "publication timing", "fundamental/event sources", "REQUIRED_IF_AVAILABLE", "BLOCKED", "Needed where source publication timing matters."),
        ("PIT-04", "run_timestamp", "fallback availability", "all active market sources", "FALLBACK_ONLY", "BLOCKED", "Only a fallback when explicit availability date is absent."),
        ("PIT-05", "source_hash", "traceability", "all active market sources", "REQUIRED", "BLOCKED", "Needed to trace PIT-safe lineage."),
        ("PIT-06", "run_id", "traceability", "all active market sources", "REQUIRED", "BLOCKED", "Needed to tie data to the binding run."),
        ("PIT-07", "signal_side_fields", "separation boundary", "normalized research dataset", "REQUIRED", "BLOCKED", "Signal-side fields cannot include future labels."),
    ]
    return [
        {
            "requirement_id": row[0],
            "field_name": row[1],
            "pit_role": row[2],
            "required_for_source_category": row[3],
            "required_status": row[4],
            "current_status": row[5],
            "blocker_reason": row[6],
        }
        for row in rows
    ]


def build_freshness_rule_plan() -> list[dict[str, object]]:
    rows = [
        ("FR-01", "current_candidate_outputs", "comparison-only historical baseline freshness", "historical snapshot age is allowed only as reference", "REFERENCE_ONLY", "FALSE", "Sealed baseline comparison data cannot become active runtime input."),
        ("FR-02", "current_ranked_candidate_outputs", "comparison-only historical baseline freshness", "historical snapshot age is allowed only as reference", "REFERENCE_ONLY", "FALSE", "Sealed baseline comparison data cannot become active runtime input."),
        ("FR-03", "current_top_candidate_outputs", "comparison-only historical baseline freshness", "historical snapshot age is allowed only as reference", "REFERENCE_ONLY", "FALSE", "Sealed baseline comparison data cannot become active runtime input."),
        ("FR-04", "price_data_outputs", "reference price overlay freshness", "reference price overlay age is allowed only for comparison", "REFERENCE_ONLY", "FALSE", "Sealed price overlays remain comparison-only."),
        ("FR-05", "v20_architecture_outputs", "architecture reference freshness", "no market-data freshness rule", "NOT_APPLICABLE", "FALSE", "Architecture outputs are not market data."),
        ("FR-06", "readable_report_outputs", "report reference freshness", "no market-data freshness rule", "NOT_APPLICABLE", "FALSE", "Readable report outputs are not market data."),
        ("FR-07", "historical_v18_baseline_outputs", "sealed baseline freshness", "historical reference only", "REFERENCE_ONLY", "FALSE", "Historical baselines remain comparison-only references."),
        ("FR-08", "historical_v19_baseline_outputs", "sealed baseline freshness", "historical reference only", "REFERENCE_ONLY", "FALSE", "Historical baselines remain comparison-only references."),
        ("FR-09", "future_normalized_dataset_placeholders", "placeholder freshness", "not real data", "PLACEHOLDER", "FALSE", "Future placeholders cannot satisfy freshness."),
    ]
    return [
        {
            "rule_id": row[0],
            "source_category": row[1],
            "freshness_rule": row[2],
            "expected_age_window": row[3],
            "current_status": row[4],
            "applies_to_active_use": row[5],
            "blocker_reason": row[6],
        }
        for row in rows
    ]


def build_leakage_control_plan() -> list[dict[str, object]]:
    rows = [
        ("LC-01", "signal-side future returns exclusion", "signal-side", "Realized future returns must never appear in signal-side fields.", "BLOCKED", "TRUE", "Future-return leakage remains blocked."),
        ("LC-02", "outcome-side isolation", "outcome dataset", "Outcome fields must be isolated to the outcome layer only.", "BLOCKED", "TRUE", "Outcome fields are design-only until the normalized dataset exists."),
        ("LC-03", "benchmark future-return exclusion", "benchmark dataset", "Benchmark future returns must not be used in signal construction.", "BLOCKED", "TRUE", "Benchmark-relative leakage remains blocked."),
        ("LC-04", "post-event label timing", "event/fundamental inputs", "Post-event labels must be blocked until the availability date.", "BLOCKED", "TRUE", "PIT timing controls are not yet implemented."),
        ("LC-05", "availability-date fallback rule", "all active market sources", "Availability date or run timestamp fallback must be explicit.", "BLOCKED", "TRUE", "Fallback rule is defined only as a plan."),
        ("LC-06", "separated comparison references", "sealed baseline reference", "Comparison-only baseline files must not be promoted to active inputs.", "BLOCKED", "TRUE", "Sealed baselines remain historical reference only."),
        ("LC-07", "future placeholder exclusion", "placeholder sources", "Future placeholders must not be treated as real data.", "BLOCKED", "TRUE", "Placeholder sources are not real data."),
    ]
    return [
        {
            "control_id": row[0],
            "control_name": row[1],
            "affected_layer": row[2],
            "control_requirement": row[3],
            "current_status": row[4],
            "must_pass_before_v20_8": row[5],
            "blocker_reason": row[6],
        }
        for row in rows
    ]


def build_sample_metadata_plan() -> list[dict[str, object]]:
    rows = [
        ("SM-01", "sample_id", "sample identity key", "required", "BLOCKED", "A stable sample_id design is required."),
        ("SM-02", "ticker", "entity identifier", "required", "BLOCKED", "Ticker linkage is required for normalized data."),
        ("SM-03", "observation_date", "signal date anchor", "required", "BLOCKED", "Observation date is required for PIT alignment."),
        ("SM-04", "source_artifact_id", "source lineage key", "required", "BLOCKED", "Source artifact lineage must be present."),
        ("SM-05", "source_hash", "hash lineage key", "required", "BLOCKED", "Source hash linkage is required."),
        ("SM-06", "run_id", "binding lineage key", "required", "BLOCKED", "Run ID linkage is required."),
        ("SM-07", "universe_membership_flag", "universe membership", "required", "BLOCKED", "Universe membership must be certified."),
        ("SM-08", "historical_reference_flag", "baseline/reference separation", "required", "BLOCKED", "Historical reference flag must separate baseline from active runtime."),
        ("SM-09", "active_runtime_flag", "runtime activation", "required", "BLOCKED", "Active runtime flag must only be set after source certification."),
    ]
    return [
        {
            "metadata_field_id": row[0],
            "metadata_field_name": row[1],
            "required_rule": row[2],
            "required_before_v20_8": row[3],
            "current_status": row[4],
            "blocker_reason": row[5],
        }
        for row in rows
    ]


def build_v208_entry_requirements() -> list[dict[str, object]]:
    rows = [
        ("ER-01", "Active PIT-ready market source certification", "V20.7R plan", "BLOCKED", "A certified active market source must exist."),
        ("ER-02", "Source registry update for active sources", "V20.5 registry", "BLOCKED", "Active runtime sources must be explicitly registered."),
        ("ER-03", "PIT date / availability metadata", "V20.7 audits", "BLOCKED", "Date and availability fields must be certified."),
        ("ER-04", "Freshness rules by source category", "V20.7R freshness plan", "BLOCKED", "Freshness must be resolved by category."),
        ("ER-05", "Leakage-safe signal/outcome separation", "V20.7R leakage plan", "BLOCKED", "Signal-side and outcome-side fields must be separated."),
        ("ER-06", "Sample metadata certification", "V20.7R sample plan", "BLOCKED", "Sample_id and lineage keys must be defined."),
        ("ER-07", "Sealed baseline isolation", "V20.7 blocker inventory", "BLOCKED", "V18/V19 baselines remain reference-only."),
        ("ER-08", "Lineage hash/run_id support", "V20.6 lineage binding", "BLOCKED", "Hash/run_id linkage must exist before normalization."),
    ]
    return [
        {
            "entry_requirement_id": row[0],
            "entry_requirement_name": row[1],
            "source_of_truth": row[2],
            "current_status": row[3],
            "blocker_reason": row[4],
        }
        for row in rows
    ]


def build_resolution_sequence() -> list[dict[str, object]]:
    rows = [
        ("01", "Keep V18/V19 sealed baseline outputs as historical reference only.", "BLOCKED", "V20.8_NORMALIZED_RESEARCH_DATASET"),
        ("02", "Certify active market source candidates with PIT-ready date, availability, and publication metadata.", "BLOCKED", "V20.8_NORMALIZED_RESEARCH_DATASET"),
        ("03", "Register active source artifacts explicitly as runtime data sources in the source registry.", "BLOCKED", "V20.8_NORMALIZED_RESEARCH_DATASET"),
        ("04", "Define sample_id and field-separation rules for the normalized research dataset.", "BLOCKED", "V20.8_NORMALIZED_RESEARCH_DATASET"),
        ("05", "Establish freshness rules by source category and source-age expectations.", "BLOCKED", "V20.8_NORMALIZED_RESEARCH_DATASET"),
        ("06", "Activate leakage controls for future returns, benchmark future returns, and post-event labels.", "BLOCKED", "V20.8_NORMALIZED_RESEARCH_DATASET"),
        ("07", "Certify sample metadata requirements and lineage binding for active sources.", "BLOCKED", "V20.8_NORMALIZED_RESEARCH_DATASET"),
        ("08", "Only then attempt V20.8 normalized research dataset creation.", "BLOCKED", "V20.8_NORMALIZED_RESEARCH_DATASET"),
    ]
    return [
        {
            "step_order": row[0],
            "resolution_action": row[1],
            "current_status": row[2],
            "target_gate": row[3],
        }
        for row in rows
    ]


def build_report(
    dependency: dict[str, str],
    blocker_rows: list[dict[str, object]],
    candidate_rows: list[dict[str, object]],
    field_rows: list[dict[str, object]],
    pit_rows: list[dict[str, object]],
    freshness_rows: list[dict[str, object]],
    leakage_rows: list[dict[str, object]],
    sample_rows: list[dict[str, object]],
    entry_rows: list[dict[str, object]],
    seq_rows: list[dict[str, object]],
    v207_blocked: bool,
    v208_allowed: bool,
) -> str:
    total_candidates = len(candidate_rows)
    usable_candidates = sum(1 for row in candidate_rows if row.get("usable_for_v20_8") == "TRUE")
    sealed_candidates = sum(1 for row in candidate_rows if row.get("historical_reference_flag") == "TRUE")
    return "\n".join(
        [
            "# V20.7R 正常化数据阻塞化解计划",
            "",
            "## 结论",
            f"- V20.7 依赖接受：{'TRUE' if dependency['dep_ok'] == 'TRUE' else 'FALSE'}",
            f"- V20.7 阻塞状态保留：{'TRUE' if v207_blocked else 'FALSE'}",
            f"- V20.8 仍然受阻：{'TRUE' if not v208_allowed else 'FALSE'}",
            "- 本步骤仅输出阻塞化解计划，不生成标准化真实研究数据行，不创建因子证据，不执行回测，不执行动态加权，不输出交易建议。",
            "",
            "## 为什么 V20.8 仍受阻",
            "- 当前运行时来源仍以架构 / 报告 / OPS / 参考性 baseline 资产为主，并没有经过认证的活跃 PIT-ready 市场数据源。",
            "- V18/V19 候选与价格文件只保留为 historical reference only，不能重新标记为 active runtime 输入。",
            "- outcome / benchmark / sample metadata 仍停留在设计计划层，不具备数据层可执行性。",
            "",
            "## 活跃市场候选结果",
            f"- 候选条目：{total_candidates}",
            f"- 仍为历史参考的候选：{sealed_candidates}",
            f"- 可直接用于 V20.8 的候选：{usable_candidates}",
            "- 结论：未发现可直接进入 V20.8 的活跃 PIT-ready 市场数据源。",
            "",
            "## 需要补齐的最小能力",
            "- active candidate / ranked / top candidate source",
            "- active price/date source",
            "- ticker 字段",
            "- observation_date / signal_date 字段",
            "- price_date / latest_price_date 字段",
            "- availability_date 或 run_timestamp 兜底规则",
            "- source_hash 链接",
            "- run_id 链接",
            "- sample_id 设计",
            "- signal-side 与 outcome-side 字段分离",
            "",
            "## 新增约束计划",
            "- freshness：按 source_category 定义不同新鲜度窗口，不允许把 sealed baseline 当作 active runtime 新鲜度来源。",
            "- leakage：禁止 signal-side 使用 realized future returns、benchmark future returns 与 post-event labels。",
            "- PIT：必须具备 observation / availability / publication 日期链路或可审计的兜底规则。",
            "- sample metadata：sample_id、ticker、observation_date、source_artifact_id、source_hash、run_id、universe_membership_flag、historical_reference_flag、active_runtime_flag。",
            "",
            "## 下一步序列",
            "- 先完成活跃市场源认证，再打开 V20.8 正常化研究数据阶段。",
            "- 在此之前，V20.8 保持 BLOCKED。",
            "",
            "## 安全边界",
            "- 不创建 normalized real data rows。",
            "- 不创建 factor evidence / backtest / dynamic weighting / trading 输出。",
            "- 不更改官方 ranking、weights 或决策逻辑。",
        ]
    )


def build_current_alias() -> str:
    return "\n".join(
        [
            "# V20 当前 normalized data blocker 状态",
            "",
            "- V20.7R 已创建，但仅作为阻塞化解计划。",
            "- V20.7 依赖已确认，且其结果仍为 BLOCKED。",
            "- V18/V19 baseline 仍为 historical reference only。",
            "- 当前没有经认证的 active PIT-ready market data。",
            "- V20.8 仍然 blocked，直到活跃市场源认证和 PIT / freshness / leakage / sample metadata 条件补齐。",
        ]
    )


def build_validation_summary(
    dependency: dict[str, str],
    blocker_rows: list[dict[str, object]],
    candidate_rows: list[dict[str, object]],
    field_rows: list[dict[str, object]],
    pit_rows: list[dict[str, object]],
    freshness_rows: list[dict[str, object]],
    leakage_rows: list[dict[str, object]],
    sample_rows: list[dict[str, object]],
    entry_rows: list[dict[str, object]],
    seq_rows: list[dict[str, object]],
    active_market_data_certified: bool,
) -> list[dict[str, object]]:
    return [
        {
            "required_outputs_created": 13,
            "dependency_inputs_found": sum(
                1
                for p in [
                    V20_7_READ_FIRST,
                    V20_7_VALIDATION,
                    V20_7_SOURCE_GATE,
                    V20_7_NORMALIZED_GATE,
                    V20_7_STALE_DATA,
                    V20_7_LEAKAGE,
                    V20_7_PIT,
                    V20_7_DATE_COVERAGE,
                    V20_7_OUTCOME_READY,
                    V20_7_BENCHMARK_READY,
                    V20_7_SAMPLE_READY,
                    V20_7_BLOCKERS,
                    V20_7_NEXT_REQ,
                    V20_6_READ_FIRST,
                    V20_6_SOURCE_HASH,
                    V20_6_INPUT_HASH,
                    V20_6_VERSION_BINDING,
                    V20_6_HASH_RUN_ID_PAIRING,
                    V20_5_SOURCE_REGISTRY,
                ]
                if p.exists()
            ),
            "v20_7_dependency_detected": dependency["dep_ok"],
            "v20_7_blocked_status_preserved": tf(not active_market_data_certified),
            "source_artifact_rows": len(source_registry_rows()),
            "blocker_inventory_rows": len(blocker_rows),
            "active_market_source_candidate_rows": len(candidate_rows),
            "required_market_field_rows": len(field_rows),
            "pit_field_plan_rows": len(pit_rows),
            "freshness_rule_plan_rows": len(freshness_rows),
            "leakage_control_plan_rows": len(leakage_rows),
            "sample_metadata_plan_rows": len(sample_rows),
            "v20_8_entry_requirement_rows": len(entry_rows),
            "resolution_sequence_rows": len(seq_rows),
            "active_market_data_certified": tf(active_market_data_certified),
            "normalized_real_data_rows_created": 0,
            "factor_evidence_created": "FALSE",
            "official_trading_signal_created": "FALSE",
            "official_portfolio_weight_created": "FALSE",
            "official_factor_weight_changed": "FALSE",
            "official_ranking_changed": "FALSE",
            "official_backtest_created": "FALSE",
            "exploratory_backtest_created": "FALSE",
            "performance_claims_created": "FALSE",
            "dynamic_weighting_executed": "FALSE",
            "source_files_mutated": "FALSE",
            "v21_started": "FALSE",
            "v19_21_started": "FALSE",
            "safety_status": "PASS",
        }
    ]


def build_read_first(dependency: dict[str, str], active_market_data_certified: bool) -> None:
    lines = [
        "STATUS: WARN",
        "PATCH_NAME: V20.7R_NORMALIZED_DATA_BLOCKER_RESOLUTION_PLAN",
        "REPORTING_ONLY: TRUE",
        "BLOCKER_RESOLUTION_PLAN_ONLY: TRUE",
        "NORMALIZED_DATA_BLOCKER_RESOLUTION_PLAN_CREATED: TRUE",
        f"STALE_LEAKAGE_PIT_DEPENDENCY_ACCEPTED: {dependency['dep_ok']}",
        "NORMALIZED_REAL_DATA_ROWS_CREATED: 0",
        "ACTIVE_MARKET_DATA_CERTIFIED: FALSE",
        "FACTOR_EVIDENCE_CREATED: FALSE",
        "OFFICIAL_TRADING_SIGNAL_CREATED: FALSE",
        "OFFICIAL_PORTFOLIO_WEIGHT_CREATED: FALSE",
        "OFFICIAL_FACTOR_WEIGHT_CHANGED: FALSE",
        "OFFICIAL_RANKING_CHANGED: FALSE",
        "OFFICIAL_BACKTEST_CREATED: FALSE",
        "EXPLORATORY_BACKTEST_CREATED: FALSE",
        "PERFORMANCE_CLAIMS_CREATED: FALSE",
        "DYNAMIC_WEIGHTING_EXECUTED: FALSE",
        "SOURCE_FILES_MUTATED: FALSE",
        "V21_STARTED: FALSE",
        "V19_21_STARTED: FALSE",
        "OFFICIAL_USE_ALLOWED: FALSE",
        "SAFETY_STATUS: PASS",
        f"READY_FOR_NORMALIZED_RESEARCH_DATASET_NEXT: {tf(active_market_data_certified)}",
        "READY_FOR_FACTOR_EVIDENCE_NEXT: FALSE",
        "READY_FOR_EXPLORATORY_BACKTEST_NEXT: FALSE",
        "READY_FOR_DYNAMIC_WEIGHTING_GATE_RESEARCH_NEXT: FALSE",
        "OFFICIAL_TRADING_ALLOWED: FALSE",
        "OFFICIAL_PORTFOLIO_WEIGHT_ALLOWED: FALSE",
        "OFFICIAL_FACTOR_WEIGHT_CHANGE_ALLOWED: FALSE",
        "OFFICIAL_BACKTEST_ALLOWED: FALSE",
        f"NEXT_RECOMMENDED_ACTION: {'V20.8_NORMALIZED_RESEARCH_DATASET' if active_market_data_certified else 'CERTIFY_ACTIVE_MARKET_SOURCES_BEFORE_V20.8'}",
        "NEXT_RECOMMENDED_MODEL: GPT-5.5",
    ]
    write_text(READ_FIRST, "\n".join(lines))


def write_outputs(
    dependency: dict[str, str],
    blocker_inventory: list[dict[str, object]],
    candidate_rows: list[dict[str, object]],
    field_rows: list[dict[str, object]],
    pit_rows: list[dict[str, object]],
    freshness_rows: list[dict[str, object]],
    leakage_rows: list[dict[str, object]],
    sample_rows: list[dict[str, object]],
    entry_rows: list[dict[str, object]],
    seq_rows: list[dict[str, object]],
    active_market_data_certified: bool,
) -> None:
    write_csv(
        OUT_BLOCKER_INVENTORY,
        blocker_inventory,
        [
            "inventory_id",
            "blocker_id",
            "blocker_category",
            "blocked_layer",
            "blocker_description",
            "current_status",
            "source_of_truth",
            "resolution_needed_before",
            "v20_8_impact",
            "plan_status",
        ],
    )
    write_csv(
        OUT_ACTIVE_SOURCE_MAP,
        candidate_rows,
        [
            "candidate_id",
            "source_artifact_id",
            "source_name",
            "source_category",
            "candidate_classification",
            "canonical_path",
            "source_status",
            "sealed_baseline",
            "current_runtime_source",
            "hash_status",
            "source_hash",
            "historical_reference_flag",
            "active_runtime_flag",
            "pit_ready_now",
            "freshness_ready_now",
            "leakage_ready_now",
            "usable_for_v20_8",
            "blocker_reason",
        ],
    )
    write_csv(
        OUT_FIELD_CONTRACT,
        field_rows,
        [
            "contract_id",
            "field_name",
            "field_role",
            "required_for_source_category",
            "required_now",
            "required_before_v20_8",
            "current_status",
            "blocker_reason",
        ],
    )
    write_csv(
        OUT_PIT_PLAN,
        pit_rows,
        [
            "requirement_id",
            "field_name",
            "pit_role",
            "required_for_source_category",
            "required_status",
            "current_status",
            "blocker_reason",
        ],
    )
    write_csv(
        OUT_FRESHNESS_PLAN,
        freshness_rows,
        [
            "rule_id",
            "source_category",
            "freshness_rule",
            "expected_age_window",
            "current_status",
            "applies_to_active_use",
            "blocker_reason",
        ],
    )
    write_csv(
        OUT_LEAKAGE_PLAN,
        leakage_rows,
        [
            "control_id",
            "control_name",
            "affected_layer",
            "control_requirement",
            "current_status",
            "must_pass_before_v20_8",
            "blocker_reason",
        ],
    )
    write_csv(
        OUT_SAMPLE_PLAN,
        sample_rows,
        [
            "metadata_field_id",
            "metadata_field_name",
            "required_rule",
            "required_before_v20_8",
            "current_status",
            "blocker_reason",
        ],
    )
    write_csv(
        OUT_ENTRY_REQ,
        entry_rows,
        [
            "entry_requirement_id",
            "entry_requirement_name",
            "source_of_truth",
            "current_status",
            "blocker_reason",
        ],
    )
    write_csv(
        OUT_SEQUENCE,
        seq_rows,
        [
            "step_order",
            "resolution_action",
            "current_status",
            "target_gate",
        ],
    )
    write_text(
        REPORT,
        build_report(
            dependency,
            blocker_inventory,
            candidate_rows,
            field_rows,
            pit_rows,
            freshness_rows,
            leakage_rows,
            sample_rows,
            entry_rows,
            seq_rows,
            dependency["dep_ok"] == "TRUE",
            active_market_data_certified,
        ),
    )
    write_text(ALIAS, build_current_alias())
    write_csv(
        OUT_VALIDATION,
        build_validation_summary(
            dependency,
            blocker_inventory,
            candidate_rows,
            field_rows,
            pit_rows,
            freshness_rows,
            leakage_rows,
            sample_rows,
            entry_rows,
            seq_rows,
            active_market_data_certified,
        ),
        [
            "required_outputs_created",
            "dependency_inputs_found",
            "v20_7_dependency_detected",
            "v20_7_blocked_status_preserved",
            "source_artifact_rows",
            "blocker_inventory_rows",
            "active_market_source_candidate_rows",
            "required_market_field_rows",
            "pit_field_plan_rows",
            "freshness_rule_plan_rows",
            "leakage_control_plan_rows",
            "sample_metadata_plan_rows",
            "v20_8_entry_requirement_rows",
            "resolution_sequence_rows",
            "active_market_data_certified",
            "normalized_real_data_rows_created",
            "factor_evidence_created",
            "official_trading_signal_created",
            "official_portfolio_weight_created",
            "official_factor_weight_changed",
            "official_ranking_changed",
            "official_backtest_created",
            "exploratory_backtest_created",
            "performance_claims_created",
            "dynamic_weighting_executed",
            "source_files_mutated",
            "v21_started",
            "v19_21_started",
            "safety_status",
        ],
    )
    build_read_first(dependency, active_market_data_certified)


def main() -> None:
    ensure_dir(CONSOLIDATION)
    ensure_dir(READ_CENTER)
    ensure_dir(OPS)

    dependency = build_dependency_state()
    v207_blockers = read_csv(V20_7_BLOCKERS)
    registry = source_registry_rows()
    candidate_rows = build_active_market_source_candidate_map(registry)

    # V20.7R is planning-only, so active market data remains uncertified.
    active_market_data_certified = False

    blocker_inventory = build_blocker_inventory(v207_blockers, active_market_data_certified)
    field_rows = build_required_market_field_contract()
    pit_rows = build_pit_field_plan()
    freshness_rows = build_freshness_rule_plan()
    leakage_rows = build_leakage_control_plan()
    sample_rows = build_sample_metadata_plan()
    entry_rows = build_v208_entry_requirements()
    seq_rows = build_resolution_sequence()

    write_outputs(
        dependency,
        blocker_inventory,
        candidate_rows,
        field_rows,
        pit_rows,
        freshness_rows,
        leakage_rows,
        sample_rows,
        entry_rows,
        seq_rows,
        active_market_data_certified,
    )


if __name__ == "__main__":
    main()
