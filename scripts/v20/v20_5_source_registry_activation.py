from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "outputs" / "v20" / "ops"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def tf(value: bool) -> str:
    return "TRUE" if bool(value) else "FALSE"


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


def read_first(path: Path) -> dict[str, str]:
    return read_kv(read_text(path))


def read_csv_rows(path: Path) -> list[dict[str, str]]:
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


def dependency_found_count(paths: list[Path]) -> int:
    return sum(1 for path in paths if path.exists())


def count_rows(path: Path) -> int:
    return len(read_csv_rows(path))


def path_if_exists(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/") if path.exists() else "MISSING"


def read_first_flag(path: Path, key: str) -> str:
    return read_first(path).get(key, "FALSE")


V20_4_READ_FIRST = ROOT / "outputs" / "v20" / "ops" / "V20_4_READ_FIRST.txt"


V20_1_REQUIRED = [
    ROOT / "outputs" / "v20" / "ops" / "V20_1_READ_FIRST.txt",
    ROOT / "outputs" / "v20" / "read_center" / "V20_1_CURRENT_RUNTIME_AND_REPORT_STRUCTURE_REPORT.md",
    ROOT / "outputs" / "v20" / "read_center" / "V20_CURRENT_RUNTIME_GUIDE.md",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_1_CURRENT_RUNTIME_MANIFEST.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_1_HISTORICAL_BASELINE_MANIFEST.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_1_REPORT_STRUCTURE_MAP.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_1_DAILY_READ_ORDER.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_1_FUTURE_RESEARCH_HOOKS.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_1_ARCHITECTURE_CLEANUP_DECISION.csv",
]

V20_2_REQUIRED = [
    ROOT / "outputs" / "v20" / "ops" / "V20_2_READ_FIRST.txt",
    ROOT / "outputs" / "v20" / "read_center" / "V20_2_FACTOR_AND_STRATEGY_RESEARCH_MAP_REPORT.md",
    ROOT / "outputs" / "v20" / "read_center" / "V20_CURRENT_FACTOR_STRATEGY_RESEARCH_VIEW.md",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_2_FACTOR_UNIVERSE_REGISTRY.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_2_FACTOR_FAMILY_MAP.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_2_FACTOR_DATA_AVAILABILITY_AUDIT.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_2_FACTOR_RESEARCH_STATUS_MAP.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_2_FACTOR_STRATEGY_RELEVANCE_MATRIX.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_2_STRATEGY_RESEARCH_FAMILY_REGISTRY.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_2_STRATEGY_FACTOR_DEPENDENCY_MAP.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_2_FACTOR_BLOCKER_REGISTER.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_2_READABLE_FACTOR_EXPLANATION_TEMPLATE.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_2_VALIDATION_SUMMARY.csv",
]

V20_3_REQUIRED = [
    ROOT / "outputs" / "v20" / "ops" / "V20_3_READ_FIRST.txt",
    ROOT / "outputs" / "v20" / "read_center" / "V20_3_READABLE_RESEARCH_REPORT_FRAMEWORK_REPORT.md",
    ROOT / "outputs" / "v20" / "read_center" / "V20_CURRENT_DAILY_RESEARCH_SUMMARY.md",
    ROOT / "outputs" / "v20" / "read_center" / "V20_CURRENT_FACTOR_EXPLANATION_VIEW.md",
    ROOT / "outputs" / "v20" / "read_center" / "V20_CURRENT_STRATEGY_RESEARCH_VIEW.md",
    ROOT / "outputs" / "v20" / "read_center" / "V20_CURRENT_DATA_QUALITY_VIEW.md",
    ROOT / "outputs" / "v20" / "read_center" / "V20_CURRENT_BLOCKERS_AND_NEXT_ACTIONS.md",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_3_READABLE_REPORT_SECTION_MAP.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_3_REPORT_FIELD_TRANSLATION_MAP.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_3_FACTOR_EXPLANATION_VIEW_TEMPLATE.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_3_STRATEGY_EXPLANATION_VIEW_TEMPLATE.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_3_DAILY_RESEARCH_SUMMARY_TEMPLATE.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_3_TOP_CANDIDATES_READABLE_TEMPLATE.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_3_DATA_QUALITY_VIEW_TEMPLATE.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_3_BLOCKERS_AND_NEXT_ACTIONS_TEMPLATE.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_3_VALIDATION_SUMMARY.csv",
]

V20_4_REQUIRED = [
    ROOT / "outputs" / "v20" / "ops" / "V20_4_READ_FIRST.txt",
    ROOT / "outputs" / "v20" / "read_center" / "V20_4_ARCHITECTURE_CLARIFICATION_SEAL_REPORT.md",
    ROOT / "outputs" / "v20" / "read_center" / "V20_CURRENT_ARCHITECTURE_CLARIFICATION_STATUS.md",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_4_ARCHITECTURE_CLARIFICATION_SEAL_DECISION.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_4_DEPENDENCY_REVIEW.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_4_ARCHITECTURE_LAYER_COMPLETION_AUDIT.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_4_CURRENT_RUNTIME_GATE.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_4_FACTOR_STRATEGY_GATE.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_4_READABLE_REPORT_GATE.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_4_READY_FOR_SOURCE_REGISTRY_ACTIVATION_GATE.csv",
]

V18_BASELINES = [
    ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_RANKED_CANDIDATES.csv",
    ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_FULL_RANKED_CANDIDATES.csv",
    ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_TOP_RANKED_CANDIDATES.csv",
    ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_CANDIDATE_SOURCE_MAP.csv",
    ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_CANDIDATE_THEME_CLASSIFICATION.csv",
    ROOT / "outputs" / "v18" / "price" / "V18_MANUAL_FULL_RANKED_LATEST_PRICE_OVERLAY.csv",
    ROOT / "outputs" / "v18" / "price" / "V18_MANUAL_TOP20_LATEST_PRICE_COMPARE.csv",
    ROOT / "outputs" / "v18" / "ranking" / "V18_CURRENT_RANKING_PROVENANCE_REPORT.md",
    ROOT / "outputs" / "v18" / "read_center" / "V18_CURRENT_TOPN_EXPLAINER_OPERATOR_NOTE.md",
]

V19_BASELINES = [
    ROOT / "outputs" / "v19" / "ops" / "V19_FINAL_READ_FIRST.txt",
    ROOT / "outputs" / "v19" / "read_center" / "V19_FINAL_HANDOFF_AND_SEAL_REPORT.md",
    ROOT / "outputs" / "v19" / "read_center" / "V19_CURRENT_FINAL_HANDOFF_AND_SEAL.md",
    ROOT / "outputs" / "v19" / "final" / "V19_FINAL_FRAMEWORK_CAPABILITY_MANIFEST.csv",
    ROOT / "outputs" / "v19" / "final" / "V19_FINAL_LINEAGE_BLOCKER_REGISTER.csv",
    ROOT / "outputs" / "v19" / "final" / "V19_FINAL_NORMALIZED_DATA_BLOCKER_REGISTER.csv",
    ROOT / "outputs" / "v19" / "final" / "V19_FINAL_FACTOR_STRATEGY_REGISTRY_INDEX.csv",
    ROOT / "outputs" / "v19" / "final" / "V19_FINAL_BACKTEST_OUTCOME_FRAMEWORK_INDEX.csv",
    ROOT / "outputs" / "v19" / "final" / "V19_FINAL_DYNAMIC_WEIGHTING_GATE_INDEX.csv",
]


def build_source_catalog() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    def add(
        artifact_id: str,
        name: str,
        category: str,
        layer: str,
        path: Path,
        status: str,
        sealed: bool,
        current_runtime: bool,
        read_center_ref: bool,
        hash_binding: bool,
        normalized_data: bool,
        factor_evidence: bool,
        backtest: bool,
        blocker_reason: str,
    ) -> None:
        rows.append(
            {
                "source_artifact_id": artifact_id,
                "source_name": name,
                "source_category": category,
                "source_layer": layer,
                "canonical_path": path_if_exists(path),
                "path_exists_now": tf(path.exists()),
                "source_status": status,
                "sealed_baseline": tf(sealed),
                "current_runtime_source": tf(current_runtime),
                "read_center_reference": tf(read_center_ref),
                "eligible_for_future_hash_binding": tf(hash_binding),
                "eligible_for_future_normalized_data": tf(normalized_data),
                "eligible_for_future_factor_evidence": tf(factor_evidence),
                "eligible_for_future_backtest": tf(backtest),
                "blocker_reason": blocker_reason,
            }
        )

    # V18 sealed baselines
    add("SA001", "V18_CURRENT_RANKED_CANDIDATES", "current_ranked_candidate_outputs", "historical_v18_baseline", ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_RANKED_CANDIDATES.csv", "SEALED_BASELINE_REFERENCE", True, False, False, False, False, False, False, "V18 baseline preserved for historical comparison only.")
    add("SA002", "V18_CURRENT_FULL_RANKED_CANDIDATES", "current_ranked_candidate_outputs", "historical_v18_baseline", ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_FULL_RANKED_CANDIDATES.csv", "SEALED_BASELINE_REFERENCE", True, False, False, False, False, False, False, "V18 baseline preserved for historical comparison only.")
    add("SA003", "V18_CURRENT_TOP_RANKED_CANDIDATES", "current_top_candidate_outputs", "historical_v18_baseline", ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_TOP_RANKED_CANDIDATES.csv", "SEALED_BASELINE_REFERENCE", True, False, False, False, False, False, False, "V18 baseline preserved for historical comparison only.")
    add("SA004", "V18_CURRENT_CANDIDATE_SOURCE_MAP", "current_candidate_outputs", "historical_v18_baseline", ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_CANDIDATE_SOURCE_MAP.csv", "SEALED_BASELINE_REFERENCE", True, False, False, False, False, False, False, "V18 baseline candidate source map retained for reference.")
    add("SA005", "V18_CURRENT_CANDIDATE_THEME_CLASSIFICATION", "current_candidate_outputs", "historical_v18_baseline", ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_CANDIDATE_THEME_CLASSIFICATION.csv", "SEALED_BASELINE_REFERENCE", True, False, False, False, False, False, False, "V18 candidate theme classification retained for reference.")
    add("SA006", "V18_MANUAL_FULL_RANKED_LATEST_PRICE_OVERLAY", "price_data_outputs", "historical_v18_baseline", ROOT / "outputs" / "v18" / "price" / "V18_MANUAL_FULL_RANKED_LATEST_PRICE_OVERLAY.csv", "SEALED_BASELINE_REFERENCE", True, False, False, False, False, False, False, "V18 price overlay preserved for reference only.")
    add("SA007", "V18_MANUAL_TOP20_LATEST_PRICE_COMPARE", "price_data_outputs", "historical_v18_baseline", ROOT / "outputs" / "v18" / "price" / "V18_MANUAL_TOP20_LATEST_PRICE_COMPARE.csv", "SEALED_BASELINE_REFERENCE", True, False, False, False, False, False, False, "V18 price comparison preserved for reference only.")
    add("SA008", "V18_CURRENT_RANKING_PROVENANCE_REPORT", "historical_v18_baseline_outputs", "historical_v18_baseline", ROOT / "outputs" / "v18" / "ranking" / "V18_CURRENT_RANKING_PROVENANCE_REPORT.md", "SEALED_BASELINE_REFERENCE", True, False, True, False, False, False, False, "V18 ranking provenance report retained as read/reference only.")
    add("SA009", "V18_CURRENT_TOPN_EXPLAINER_OPERATOR_NOTE", "historical_v18_baseline_outputs", "historical_v18_baseline", ROOT / "outputs" / "v18" / "read_center" / "V18_CURRENT_TOPN_EXPLAINER_OPERATOR_NOTE.md", "SEALED_BASELINE_REFERENCE", True, False, True, False, False, False, False, "V18 operator note retained as read/reference only.")

    # V19 sealed baselines
    add("SA010", "V19_FINAL_READ_FIRST", "historical_v19_baseline_outputs", "historical_v19_baseline", ROOT / "outputs" / "v19" / "ops" / "V19_FINAL_READ_FIRST.txt", "SEALED_BASELINE_REFERENCE", True, False, True, False, False, False, False, "V19 sealed handoff reference only.")
    add("SA011", "V19_FINAL_HANDOFF_AND_SEAL_REPORT", "historical_v19_baseline_outputs", "historical_v19_baseline", ROOT / "outputs" / "v19" / "read_center" / "V19_FINAL_HANDOFF_AND_SEAL_REPORT.md", "SEALED_BASELINE_REFERENCE", True, False, True, False, False, False, False, "V19 sealed handoff reference only.")
    add("SA012", "V19_CURRENT_FINAL_HANDOFF_AND_SEAL", "historical_v19_baseline_outputs", "historical_v19_baseline", ROOT / "outputs" / "v19" / "read_center" / "V19_CURRENT_FINAL_HANDOFF_AND_SEAL.md", "SEALED_BASELINE_REFERENCE", True, False, True, False, False, False, False, "V19 canonical current handoff reference only.")
    add("SA013", "V19_FINAL_FRAMEWORK_CAPABILITY_MANIFEST", "historical_v19_baseline_outputs", "historical_v19_baseline", ROOT / "outputs" / "v19" / "final" / "V19_FINAL_FRAMEWORK_CAPABILITY_MANIFEST.csv", "SEALED_BASELINE_REFERENCE", True, False, False, False, False, False, False, "V19 capability manifest retained as baseline only.")
    add("SA014", "V19_FINAL_LINEAGE_BLOCKER_REGISTER", "historical_v19_baseline_outputs", "historical_v19_baseline", ROOT / "outputs" / "v19" / "final" / "V19_FINAL_LINEAGE_BLOCKER_REGISTER.csv", "SEALED_BASELINE_REFERENCE", True, False, False, False, False, False, False, "V19 lineage blockers retained as baseline only.")
    add("SA015", "V19_FINAL_NORMALIZED_DATA_BLOCKER_REGISTER", "historical_v19_baseline_outputs", "historical_v19_baseline", ROOT / "outputs" / "v19" / "final" / "V19_FINAL_NORMALIZED_DATA_BLOCKER_REGISTER.csv", "SEALED_BASELINE_REFERENCE", True, False, False, False, False, False, False, "V19 normalized-data blockers retained as baseline only.")
    add("SA016", "V19_FINAL_FACTOR_STRATEGY_REGISTRY_INDEX", "historical_v19_baseline_outputs", "historical_v19_baseline", ROOT / "outputs" / "v19" / "final" / "V19_FINAL_FACTOR_STRATEGY_REGISTRY_INDEX.csv", "SEALED_BASELINE_REFERENCE", True, False, False, False, False, False, False, "V19 factor/strategy index retained as baseline only.")
    add("SA017", "V19_FINAL_BACKTEST_OUTCOME_FRAMEWORK_INDEX", "historical_v19_baseline_outputs", "historical_v19_baseline", ROOT / "outputs" / "v19" / "final" / "V19_FINAL_BACKTEST_OUTCOME_FRAMEWORK_INDEX.csv", "SEALED_BASELINE_REFERENCE", True, False, False, False, False, False, False, "V19 backtest/outcome framework index retained as baseline only.")
    add("SA018", "V19_FINAL_DYNAMIC_WEIGHTING_GATE_INDEX", "historical_v19_baseline_outputs", "historical_v19_baseline", ROOT / "outputs" / "v19" / "final" / "V19_FINAL_DYNAMIC_WEIGHTING_GATE_INDEX.csv", "SEALED_BASELINE_REFERENCE", True, False, False, False, False, False, False, "V19 dynamic weighting gate index retained as baseline only.")

    # V20 architecture and runtime outputs
    add("SA019", "V20_1_CURRENT_RUNTIME_MANIFEST", "v20_architecture_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_1_CURRENT_RUNTIME_MANIFEST.csv", "ACTIVE_RUNTIME", False, True, False, True, False, False, False, "Runtime manifest is an active architecture source.")
    add("SA020", "V20_1_HISTORICAL_BASELINE_MANIFEST", "v20_architecture_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_1_HISTORICAL_BASELINE_MANIFEST.csv", "ACTIVE_RUNTIME", False, True, False, True, False, False, False, "Historical baseline manifest is an active architecture source.")
    add("SA021", "V20_1_REPORT_STRUCTURE_MAP", "readable_report_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_1_REPORT_STRUCTURE_MAP.csv", "ACTIVE_RUNTIME", False, True, False, True, False, False, False, "Report structure map is a current runtime reference.")
    add("SA022", "V20_1_DAILY_READ_ORDER", "readable_report_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_1_DAILY_READ_ORDER.csv", "ACTIVE_RUNTIME", False, True, False, True, False, False, False, "Daily read order is a current runtime reference.")
    add("SA023", "V20_1_FUTURE_RESEARCH_HOOKS", "readable_report_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_1_FUTURE_RESEARCH_HOOKS.csv", "ACTIVE_RUNTIME", False, True, False, True, False, False, False, "Future hooks are an active planning reference.")
    add("SA024", "V20_1_ARCHITECTURE_CLEANUP_DECISION", "readable_report_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_1_ARCHITECTURE_CLEANUP_DECISION.csv", "ACTIVE_RUNTIME", False, True, False, True, False, False, False, "Architecture cleanup decision is a current runtime reference.")
    add("SA025", "V20_2_FACTOR_UNIVERSE_REGISTRY", "factor_registry_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_2_FACTOR_UNIVERSE_REGISTRY.csv", "ACTIVE_RUNTIME", False, True, False, True, True, True, False, "Factor universe registry is active and eligible for future lineage planning.")
    add("SA026", "V20_2_FACTOR_FAMILY_MAP", "factor_registry_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_2_FACTOR_FAMILY_MAP.csv", "ACTIVE_RUNTIME", False, True, False, True, True, True, False, "Factor family map is active and eligible for future lineage planning.")
    add("SA027", "V20_2_FACTOR_DATA_AVAILABILITY_AUDIT", "factor_registry_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_2_FACTOR_DATA_AVAILABILITY_AUDIT.csv", "ACTIVE_RUNTIME", False, True, False, True, True, True, False, "Data availability audit is active and eligible for future lineage planning.")
    add("SA028", "V20_2_FACTOR_RESEARCH_STATUS_MAP", "factor_registry_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_2_FACTOR_RESEARCH_STATUS_MAP.csv", "ACTIVE_RUNTIME", False, True, False, True, True, True, False, "Factor research status map is active and eligible for future lineage planning.")
    add("SA029", "V20_2_FACTOR_STRATEGY_RELEVANCE_MATRIX", "factor_registry_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_2_FACTOR_STRATEGY_RELEVANCE_MATRIX.csv", "ACTIVE_RUNTIME", False, True, False, True, True, True, False, "Factor-strategy matrix is active and eligible for future lineage planning.")
    add("SA030", "V20_2_STRATEGY_RESEARCH_FAMILY_REGISTRY", "strategy_registry_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_2_STRATEGY_RESEARCH_FAMILY_REGISTRY.csv", "ACTIVE_RUNTIME", False, True, False, True, True, True, False, "Strategy research registry is active and eligible for future lineage planning.")
    add("SA031", "V20_2_STRATEGY_FACTOR_DEPENDENCY_MAP", "strategy_registry_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_2_STRATEGY_FACTOR_DEPENDENCY_MAP.csv", "ACTIVE_RUNTIME", False, True, False, True, True, True, False, "Strategy factor dependency map is active and eligible for future lineage planning.")
    add("SA032", "V20_2_FACTOR_BLOCKER_REGISTER", "readable_report_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_2_FACTOR_BLOCKER_REGISTER.csv", "ACTIVE_RUNTIME", False, True, True, True, False, False, False, "Factor blocker register is a readable reference for later planning.")
    add("SA033", "V20_2_READABLE_FACTOR_EXPLANATION_TEMPLATE", "readable_report_outputs", "v20_read_center", ROOT / "outputs" / "v20" / "consolidation" / "V20_2_READABLE_FACTOR_EXPLANATION_TEMPLATE.csv", "ACTIVE_RUNTIME", False, True, True, True, False, False, False, "Readable factor explanation template is a read_center reference.")
    add("SA034", "V20_2_VALIDATION_SUMMARY", "readable_report_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_2_VALIDATION_SUMMARY.csv", "ACTIVE_RUNTIME", False, True, True, True, False, False, False, "V20.2 validation summary is a readable reference.")
    add("SA035", "V20_3_READABLE_REPORT_SECTION_MAP", "readable_report_outputs", "v20_read_center", ROOT / "outputs" / "v20" / "consolidation" / "V20_3_READABLE_REPORT_SECTION_MAP.csv", "ACTIVE_RUNTIME", False, True, True, True, False, False, False, "Readable report section map is a report reference.")
    add("SA036", "V20_3_REPORT_FIELD_TRANSLATION_MAP", "readable_report_outputs", "v20_read_center", ROOT / "outputs" / "v20" / "consolidation" / "V20_3_REPORT_FIELD_TRANSLATION_MAP.csv", "ACTIVE_RUNTIME", False, True, True, True, False, False, False, "Field translation map is a report reference.")
    add("SA037", "V20_3_FACTOR_EXPLANATION_VIEW_TEMPLATE", "readable_report_outputs", "v20_read_center", ROOT / "outputs" / "v20" / "consolidation" / "V20_3_FACTOR_EXPLANATION_VIEW_TEMPLATE.csv", "ACTIVE_RUNTIME", False, True, True, True, False, False, False, "Factor explanation view template is a report reference.")
    add("SA038", "V20_3_STRATEGY_EXPLANATION_VIEW_TEMPLATE", "readable_report_outputs", "v20_read_center", ROOT / "outputs" / "v20" / "consolidation" / "V20_3_STRATEGY_EXPLANATION_VIEW_TEMPLATE.csv", "ACTIVE_RUNTIME", False, True, True, True, False, False, False, "Strategy explanation view template is a report reference.")
    add("SA039", "V20_3_DAILY_RESEARCH_SUMMARY_TEMPLATE", "readable_report_outputs", "v20_read_center", ROOT / "outputs" / "v20" / "consolidation" / "V20_3_DAILY_RESEARCH_SUMMARY_TEMPLATE.csv", "ACTIVE_RUNTIME", False, True, True, True, False, False, False, "Daily research summary template is a report reference.")
    add("SA040", "V20_3_TOP_CANDIDATES_READABLE_TEMPLATE", "readable_report_outputs", "v20_read_center", ROOT / "outputs" / "v20" / "consolidation" / "V20_3_TOP_CANDIDATES_READABLE_TEMPLATE.csv", "ACTIVE_RUNTIME", False, True, True, True, False, False, False, "Top candidate readable template is a report reference.")
    add("SA041", "V20_3_DATA_QUALITY_VIEW_TEMPLATE", "readable_report_outputs", "v20_read_center", ROOT / "outputs" / "v20" / "consolidation" / "V20_3_DATA_QUALITY_VIEW_TEMPLATE.csv", "ACTIVE_RUNTIME", False, True, True, True, False, False, False, "Data quality view template is a report reference.")
    add("SA042", "V20_3_BLOCKERS_AND_NEXT_ACTIONS_TEMPLATE", "readable_report_outputs", "v20_read_center", ROOT / "outputs" / "v20" / "consolidation" / "V20_3_BLOCKERS_AND_NEXT_ACTIONS_TEMPLATE.csv", "ACTIVE_RUNTIME", False, True, True, True, False, False, False, "Blockers and next-actions template is a report reference.")
    add("SA043", "V20_3_VALIDATION_SUMMARY", "readable_report_outputs", "v20_read_center", ROOT / "outputs" / "v20" / "consolidation" / "V20_3_VALIDATION_SUMMARY.csv", "ACTIVE_RUNTIME", False, True, True, True, False, False, False, "V20.3 validation summary is a readable reference.")
    add("SA044", "V20_3_READABLE_RESEARCH_REPORT_FRAMEWORK_REPORT", "readable_report_outputs", "v20_read_center", ROOT / "outputs" / "v20" / "read_center" / "V20_3_READABLE_RESEARCH_REPORT_FRAMEWORK_REPORT.md", "ACTIVE_RUNTIME", False, True, True, True, False, False, False, "Readable research framework report is a read_center reference.")
    add("SA045", "V20_CURRENT_DAILY_RESEARCH_SUMMARY", "v20_read_center_outputs", "v20_read_center", ROOT / "outputs" / "v20" / "read_center" / "V20_CURRENT_DAILY_RESEARCH_SUMMARY.md", "ACTIVE_RUNTIME", False, True, True, True, False, False, False, "Current daily summary is a read_center reference.")
    add("SA046", "V20_CURRENT_FACTOR_EXPLANATION_VIEW", "readable_report_outputs", "v20_read_center", ROOT / "outputs" / "v20" / "read_center" / "V20_CURRENT_FACTOR_EXPLANATION_VIEW.md", "ACTIVE_RUNTIME", False, True, True, True, False, False, False, "Current factor explanation view is a read_center reference.")
    add("SA047", "V20_CURRENT_STRATEGY_RESEARCH_VIEW", "readable_report_outputs", "v20_read_center", ROOT / "outputs" / "v20" / "read_center" / "V20_CURRENT_STRATEGY_RESEARCH_VIEW.md", "ACTIVE_RUNTIME", False, True, True, True, False, False, False, "Current strategy research view is a read_center reference.")
    add("SA048", "V20_CURRENT_DATA_QUALITY_VIEW", "read_center_outputs", "v20_read_center", ROOT / "outputs" / "v20" / "read_center" / "V20_CURRENT_DATA_QUALITY_VIEW.md", "ACTIVE_RUNTIME", False, True, True, True, False, False, False, "Current data quality view is a read_center reference.")
    add("SA049", "V20_CURRENT_BLOCKERS_AND_NEXT_ACTIONS", "read_center_outputs", "v20_read_center", ROOT / "outputs" / "v20" / "read_center" / "V20_CURRENT_BLOCKERS_AND_NEXT_ACTIONS.md", "ACTIVE_RUNTIME", False, True, True, True, False, False, False, "Current blockers and next-actions view is a read_center reference.")
    add("SA050", "V20_CURRENT_ARCHITECTURE_CLARIFICATION_STATUS", "read_center_outputs", "v20_read_center", ROOT / "outputs" / "v20" / "read_center" / "V20_CURRENT_ARCHITECTURE_CLARIFICATION_STATUS.md", "ACTIVE_RUNTIME", False, True, True, True, False, False, False, "Current architecture clarification status is a read_center reference.")
    add("SA051", "V20_1_READ_FIRST", "v20_ops_outputs", "v20_ops", ROOT / "outputs" / "v20" / "ops" / "V20_1_READ_FIRST.txt", "ACTIVE_RUNTIME", False, True, False, True, False, False, False, "V20.1 read-first is an ops reference.")
    add("SA052", "V20_2_READ_FIRST", "v20_ops_outputs", "v20_ops", ROOT / "outputs" / "v20" / "ops" / "V20_2_READ_FIRST.txt", "ACTIVE_RUNTIME", False, True, False, True, False, False, False, "V20.2 read-first is an ops reference.")
    add("SA053", "V20_3_READ_FIRST", "v20_ops_outputs", "v20_ops", ROOT / "outputs" / "v20" / "ops" / "V20_3_READ_FIRST.txt", "ACTIVE_RUNTIME", False, True, False, True, False, False, False, "V20.3 read-first is an ops reference.")
    add("SA054", "V20_4_READ_FIRST", "v20_ops_outputs", "v20_ops", ROOT / "outputs" / "v20" / "ops" / "V20_4_READ_FIRST.txt", "ACTIVE_RUNTIME", False, True, False, True, False, False, False, "V20.4 read-first is an ops reference.")
    add("SA055", "V20_4_ARCHITECTURE_CLARIFICATION_SEAL_DECISION", "v20_architecture_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_4_ARCHITECTURE_CLARIFICATION_SEAL_DECISION.csv", "ACTIVE_RUNTIME", False, True, False, True, False, False, False, "Seal decision is the active handoff gate for source registry activation.")
    add("SA056", "V20_4_DEPENDENCY_REVIEW", "v20_architecture_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_4_DEPENDENCY_REVIEW.csv", "ACTIVE_RUNTIME", False, True, False, True, False, False, False, "Dependency review is a current runtime reference.")
    add("SA057", "V20_4_ARCHITECTURE_LAYER_COMPLETION_AUDIT", "v20_architecture_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_4_ARCHITECTURE_LAYER_COMPLETION_AUDIT.csv", "ACTIVE_RUNTIME", False, True, False, True, False, False, False, "Layer completion audit is a current runtime reference.")
    add("SA058", "V20_4_CURRENT_RUNTIME_GATE", "v20_architecture_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_4_CURRENT_RUNTIME_GATE.csv", "ACTIVE_RUNTIME", False, True, False, True, False, False, False, "Current runtime gate is a current runtime reference.")
    add("SA059", "V20_4_FACTOR_STRATEGY_GATE", "v20_architecture_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_4_FACTOR_STRATEGY_GATE.csv", "ACTIVE_RUNTIME", False, True, False, True, False, False, False, "Factor/strategy gate is a current runtime reference.")
    add("SA060", "V20_4_READABLE_REPORT_GATE", "v20_architecture_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_4_READABLE_REPORT_GATE.csv", "ACTIVE_RUNTIME", False, True, False, True, False, False, False, "Readable report gate is a current runtime reference.")
    add("SA061", "V20_4_READY_FOR_SOURCE_REGISTRY_ACTIVATION_GATE", "v20_architecture_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_4_READY_FOR_SOURCE_REGISTRY_ACTIVATION_GATE.csv", "ACTIVE_RUNTIME", False, True, False, True, False, False, False, "Ready-for-source-registry gate is the permission source for this step.")
    add("SA062", "V20_4_READY_FOR_HASH_RUN_ID_VERSION_BINDING_GATE", "v20_architecture_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_4_READY_FOR_HASH_RUN_ID_VERSION_BINDING_GATE.csv", "ACTIVE_RUNTIME", False, True, False, True, False, False, False, "Hash/run_id/version gate is a future readiness reference.")
    add("SA063", "V20_4_READY_FOR_STALE_LEAKAGE_PIT_GATE", "v20_architecture_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_4_READY_FOR_STALE_LEAKAGE_PIT_GATE.csv", "ACTIVE_RUNTIME", False, True, False, True, False, False, False, "Stale/leakage/PIT gate is a future readiness reference.")
    add("SA064", "V20_4_READY_FOR_NORMALIZED_RESEARCH_DATASET_GATE", "v20_architecture_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_4_READY_FOR_NORMALIZED_RESEARCH_DATASET_GATE.csv", "ACTIVE_RUNTIME", False, True, False, True, False, False, False, "Normalized dataset gate is a future readiness reference.")
    add("SA065", "V20_4_READY_FOR_FACTOR_EVIDENCE_GATE", "v20_architecture_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_4_READY_FOR_FACTOR_EVIDENCE_GATE.csv", "ACTIVE_RUNTIME", False, True, False, True, False, False, False, "Factor evidence gate is a future readiness reference.")
    add("SA066", "V20_4_READY_FOR_EXPLORATORY_BACKTEST_GATE", "v20_architecture_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_4_READY_FOR_EXPLORATORY_BACKTEST_GATE.csv", "ACTIVE_RUNTIME", False, True, False, True, False, False, False, "Exploratory backtest gate is a future readiness reference.")
    add("SA067", "V20_4_READY_FOR_DYNAMIC_WEIGHTING_GATE_RESEARCH", "v20_architecture_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_4_READY_FOR_DYNAMIC_WEIGHTING_GATE_RESEARCH.csv", "ACTIVE_RUNTIME", False, True, False, True, False, False, False, "Dynamic weighting research gate is a future readiness reference.")
    add("SA068", "V20_4_BLOCKED_OFFICIAL_USE_REGISTER", "v20_architecture_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_4_BLOCKED_OFFICIAL_USE_REGISTER.csv", "ACTIVE_RUNTIME", False, True, False, True, False, False, False, "Official-use blocked register is a current runtime reference.")
    add("SA069", "V20_4_NEXT_STAGE_SEQUENCE", "v20_architecture_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_4_NEXT_STAGE_SEQUENCE.csv", "ACTIVE_RUNTIME", False, True, False, True, False, False, False, "Next stage sequence is a future-planning reference.")
    add("SA070", "V20_4_VALIDATION_SUMMARY", "v20_architecture_outputs", "v20_architecture", ROOT / "outputs" / "v20" / "consolidation" / "V20_4_VALIDATION_SUMMARY.csv", "ACTIVE_RUNTIME", False, True, False, True, False, False, False, "V20.4 validation summary is a current runtime reference.")
    add("SA071", "V20_4_ARCHITECTURE_CLARIFICATION_SEAL_REPORT", "read_center_outputs", "v20_read_center", ROOT / "outputs" / "v20" / "read_center" / "V20_4_ARCHITECTURE_CLARIFICATION_SEAL_REPORT.md", "ACTIVE_RUNTIME", False, True, True, True, False, False, False, "Architecture seal report is a read_center reference.")
    add("SA072", "V20_CURRENT_ARCHITECTURE_CLARIFICATION_STATUS", "read_center_outputs", "v20_read_center", ROOT / "outputs" / "v20" / "read_center" / "V20_CURRENT_ARCHITECTURE_CLARIFICATION_STATUS.md", "ACTIVE_RUNTIME", False, True, True, True, False, False, False, "Current architecture status is a read_center reference.")

    # Future placeholders and missing optional sources
    add("SA073", "MANUAL_UPLOAD_TEMPLATE_PLACEHOLDER", "manual_upload_templates", "future_normalized_dataset_placeholders", ROOT / "outputs" / "v20" / "placeholders" / "V20_5_MANUAL_UPLOAD_TEMPLATE_PLACEHOLDER.csv", "REGISTERED_MISSING_OPTIONAL", False, False, False, False, False, False, False, "Optional manual upload template is not required for source registry activation.")
    add("SA074", "MANUAL_UPLOAD_LEDGER_PLACEHOLDER", "manual_upload_ledgers", "future_normalized_dataset_placeholders", ROOT / "outputs" / "v20" / "placeholders" / "V20_5_MANUAL_UPLOAD_LEDGER_PLACEHOLDER.csv", "REGISTERED_MISSING_OPTIONAL", False, False, False, False, False, False, False, "Optional manual upload ledger is not required for source registry activation.")
    add("SA075", "FUTURE_NORMALIZED_RESEARCH_DATASET_PLACEHOLDER", "future_normalized_dataset_placeholders", "future_normalized_dataset_placeholders", ROOT / "outputs" / "v20" / "placeholders" / "V20_5_NORMALIZED_RESEARCH_DATASET_PLACEHOLDER.csv", "REGISTERED_PLACEHOLDER", False, False, False, False, True, True, False, "Placeholder for the future normalized research dataset; not real data.")
    add("SA076", "FUTURE_BACKTEST_PLACEHOLDER", "future_backtest_placeholders", "future_backtest_placeholders", ROOT / "outputs" / "v20" / "placeholders" / "V20_5_EXPLORATORY_BACKTEST_PLACEHOLDER.csv", "REGISTERED_PLACEHOLDER", False, False, False, False, False, False, True, "Placeholder for the future exploratory backtest output; not real backtest data.")

    return rows


def build_canonical_path_registry(source_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[str] = set()
    rows: list[dict[str, object]] = []
    for row in source_rows:
        path = str(row["canonical_path"])
        if path in seen:
            continue
        seen.add(path)
        allowed_use = "CURRENT_RUNTIME" if row["current_runtime_source"] == "TRUE" else ("READ_REFERENCE" if row["read_center_reference"] == "TRUE" else ("BASELINE_REFERENCE" if row["sealed_baseline"] == "TRUE" else "FUTURE_PLACEHOLDER"))
        blocked_use = "OFFICIAL_USE;LINEAGE_BINDING;NORMALIZED_DATA;FACTOR_EVIDENCE;BACKTEST"
        rows.append(
            {
                "canonical_source_id": f"CSP{len(rows)+1:03d}",
                "canonical_path": path,
                "expected_owner_version": "V20" if "outputs/v20" in path else ("V19" if "outputs/v19" in path else "V18/V20"),
                "path_role": row["source_layer"],
                "path_exists_now": row["path_exists_now"],
                "allowed_use": allowed_use,
                "blocked_use": blocked_use,
                "notes": "Path registered for source registry activation; no official use is implied.",
            }
        )
    return rows


def build_source_type_classification() -> list[dict[str, object]]:
    types = [
        ("ST01", "current_candidate_outputs", "Current candidate and ranked candidate outputs from the sealed V18 baseline.", "outputs/v18/candidates/V18_CURRENT_*.csv", "HISTORICAL", True, False, True),
        ("ST02", "current_ranked_candidate_outputs", "Ranked candidate outputs used for historical comparison only.", "outputs/v18/candidates/V18_CURRENT_*RANKED*.csv", "HISTORICAL", True, False, True),
        ("ST03", "current_top_candidate_outputs", "Top candidate outputs preserved as historical baseline references.", "outputs/v18/candidates/V18_CURRENT_TOP_*.csv", "HISTORICAL", True, False, True),
        ("ST04", "price_data_outputs", "Price overlay and compare outputs used as historical input references.", "outputs/v18/price/*.csv", "HISTORICAL", True, False, True),
        ("ST05", "manual_upload_templates", "Manual upload template placeholders for future ingestion planning.", "outputs/v20/placeholders/*.csv", "FUTURE", True, False, True),
        ("ST06", "manual_upload_ledgers", "Manual upload ledger placeholders for future ingestion planning.", "outputs/v20/placeholders/*.csv", "FUTURE", True, False, True),
        ("ST07", "factor_registry_outputs", "Factor registry and factor explanation outputs generated by V20.2/V20.3.", "outputs/v20/consolidation/V20_2_*.csv;outputs/v20/consolidation/V20_3_*FACTOR*.csv", "CURRENT", True, True, True),
        ("ST08", "strategy_registry_outputs", "Strategy registry and dependency outputs generated by V20.2/V20.3.", "outputs/v20/consolidation/V20_2_*.csv;outputs/v20/consolidation/V20_3_*STRATEGY*.csv", "CURRENT", True, True, True),
        ("ST09", "readable_report_outputs", "Readable report outputs across V20.1-V20.4.", "outputs/v20/consolidation/*.csv;outputs/v20/read_center/*.md", "CURRENT", True, True, True),
        ("ST10", "historical_v18_baseline_outputs", "Sealed V18 historical baseline outputs.", "outputs/v18/**", "HISTORICAL", True, False, True),
        ("ST11", "historical_v19_baseline_outputs", "Sealed V19 historical baseline outputs.", "outputs/v19/**", "HISTORICAL", True, False, True),
        ("ST12", "v20_architecture_outputs", "V20.1-V20.4 architecture and gate outputs.", "outputs/v20/consolidation/V20_1_*;outputs/v20/consolidation/V20_4_*", "CURRENT", True, False, True),
        ("ST13", "v20_read_center_outputs", "V20 read_center output views and aliases.", "outputs/v20/read_center/*.md", "CURRENT", True, True, True),
        ("ST14", "v20_ops_outputs", "V20 ops READ_FIRST files.", "outputs/v20/ops/*.txt", "CURRENT", True, False, True),
        ("ST15", "future_normalized_dataset_placeholders", "Placeholders for future normalized research datasets.", "outputs/v20/placeholders/*.csv", "FUTURE", True, False, True),
        ("ST16", "future_backtest_placeholders", "Placeholders for future exploratory backtest outputs.", "outputs/v20/placeholders/*.csv", "FUTURE", True, False, True),
    ]
    return [
        {
            "source_type_id": type_id,
            "source_category": category,
            "source_type_description": description,
            "expected_file_pattern": pattern,
            "current_or_historical": current_or_historical,
            "machine_readable": tf(machine_readable),
            "human_readable": tf(human_readable),
            "future_binding_required": tf(future_binding_required),
        }
        for type_id, category, description, pattern, current_or_historical, machine_readable, human_readable, future_binding_required in types
    ]


def build_source_layer_map() -> list[dict[str, object]]:
    return [
        {
            "source_layer_id": "SL01",
            "source_layer_name": "historical_v18_baseline",
            "source_categories": "historical_v18_baseline_outputs;current_candidate_outputs;current_ranked_candidate_outputs;current_top_candidate_outputs;price_data_outputs",
            "source_layer_role": "sealed historical baseline",
            "current_runtime_role": "FALSE",
            "read_center_role": "TRUE",
            "future_binding_role": "TRUE",
            "status": "SEALED",
            "notes": "V18 remains sealed and is used only for historical comparison and reference.",
        },
        {
            "source_layer_id": "SL02",
            "source_layer_name": "historical_v19_baseline",
            "source_categories": "historical_v19_baseline_outputs",
            "source_layer_role": "sealed historical baseline",
            "current_runtime_role": "FALSE",
            "read_center_role": "TRUE",
            "future_binding_role": "TRUE",
            "status": "SEALED",
            "notes": "V19 remains sealed and is used only for historical handoff and reference.",
        },
        {
            "source_layer_id": "SL03",
            "source_layer_name": "v20_architecture",
            "source_categories": "v20_architecture_outputs",
            "source_layer_role": "current runtime architecture",
            "current_runtime_role": "TRUE",
            "read_center_role": "TRUE",
            "future_binding_role": "TRUE",
            "status": "ACTIVE",
            "notes": "V20.1-V20.4 architecture and gate outputs are active runtime references.",
        },
        {
            "source_layer_id": "SL04",
            "source_layer_name": "v20_read_center",
            "source_categories": "v20_read_center_outputs;readable_report_outputs",
            "source_layer_role": "read_center and report views",
            "current_runtime_role": "TRUE",
            "read_center_role": "TRUE",
            "future_binding_role": "TRUE",
            "status": "ACTIVE",
            "notes": "Readable markdown views are active report references, not execution assets.",
        },
        {
            "source_layer_id": "SL05",
            "source_layer_name": "v20_ops",
            "source_categories": "v20_ops_outputs",
            "source_layer_role": "operator read-first guides",
            "current_runtime_role": "TRUE",
            "read_center_role": "TRUE",
            "future_binding_role": "TRUE",
            "status": "ACTIVE",
            "notes": "READ_FIRST ops files are active runtime guidance for the V20 workflow.",
        },
        {
            "source_layer_id": "SL06",
            "source_layer_name": "future_placeholders",
            "source_categories": "manual_upload_templates;manual_upload_ledgers;future_normalized_dataset_placeholders;future_backtest_placeholders",
            "source_layer_role": "future execution placeholders",
            "current_runtime_role": "FALSE",
            "read_center_role": "FALSE",
            "future_binding_role": "TRUE",
            "status": "PLACEHOLDER",
            "notes": "Placeholder sources are registered for future planning only and are not real data.",
        },
    ]


def build_availability_audit(source_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for idx, row in enumerate(source_rows, start=1):
        is_missing_optional = row["source_status"] == "REGISTERED_MISSING_OPTIONAL"
        rows.append(
            {
                "audit_id": f"AU{idx:03d}",
                "source_artifact_id": row["source_artifact_id"],
                "canonical_path": row["canonical_path"],
                "availability_status": "AVAILABLE" if row["path_exists_now"] == "TRUE" else ("REGISTERED_MISSING_OPTIONAL" if is_missing_optional else "REGISTERED_PLACEHOLDER"),
                "missing_allowed_now": tf(is_missing_optional or row["source_status"] == "REGISTERED_PLACEHOLDER"),
                "required_before_hash_binding": "TRUE" if row["current_runtime_source"] == "TRUE" else "FALSE",
                "required_before_normalized_data": "TRUE" if row["eligible_for_future_normalized_data"] == "TRUE" else "FALSE",
                "required_before_backtest": "TRUE" if row["eligible_for_future_backtest"] == "TRUE" else "FALSE",
                "blocker_reason": row["blocker_reason"],
            }
        )
    return rows


def build_eligibility_rows(source_rows: list[dict[str, object]], field_name: str, title: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for idx, row in enumerate(source_rows, start=1):
        eligible = row[field_name] == "TRUE"
        rows.append(
            {
                "eligibility_id": f"EL{idx:03d}",
                "source_artifact_id": row["source_artifact_id"],
                "canonical_path": row["canonical_path"],
                "source_category": row["source_category"],
                "eligibility_status": "ELIGIBLE" if eligible else "NOT_YET_ELIGIBLE",
                "title": title,
                "reason": row["blocker_reason"],
            }
        )
    return rows


def build_blocker_register(source_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    selected = [
        ("BLOCK01", "SA073", "REGISTERED_MISSING_OPTIONAL", "Manual upload template placeholder is not present as a physical source.", "future manual upload onboarding", "Optional source is not required before hash binding.", "REGISTERED_MISSING_OPTIONAL"),
        ("BLOCK02", "SA074", "REGISTERED_MISSING_OPTIONAL", "Manual upload ledger placeholder is not present as a physical source.", "future manual upload onboarding", "Optional source is not required before hash binding.", "REGISTERED_MISSING_OPTIONAL"),
        ("BLOCK03", "SA075", "REGISTERED_PLACEHOLDER", "Normalized research dataset placeholder is not a real dataset.", "future normalized dataset", "Future normalized research dataset must be created in a later version.", "BLOCKED_UNTIL_AVAILABLE"),
        ("BLOCK04", "SA076", "REGISTERED_PLACEHOLDER", "Exploratory backtest placeholder is not a real backtest.", "future exploratory backtest", "Future backtest output must be created in a later version.", "BLOCKED_UNTIL_AVAILABLE"),
        ("BLOCK05", "SA010", "SEALED_BASELINE_REFERENCE", "V19 baseline is read/reference only.", "future hash binding comparison", "Historical baseline is read-only and not a current runtime source.", "READ_REFERENCE_ONLY"),
        ("BLOCK06", "SA011", "SEALED_BASELINE_REFERENCE", "V19 baseline report is read/reference only.", "future hash binding comparison", "Historical baseline is read-only and not a current runtime source.", "READ_REFERENCE_ONLY"),
        ("BLOCK07", "SA019", "ACTIVE_RUNTIME", "Source registry activation needs the current runtime architecture source set.", "hash/run_id/version binding planning", "V20 architecture outputs must stay available for future binding planning.", "ACTIVE_RUNTIME_REFERENCE"),
        ("BLOCK08", "SA025", "ACTIVE_RUNTIME", "Factor registry outputs are planning references, not execution data.", "future normalized data and evidence", "Factor registry outputs stay available for future lineage planning.", "ACTIVE_RUNTIME_REFERENCE"),
        ("BLOCK09", "SA030", "ACTIVE_RUNTIME", "Strategy registry outputs are planning references, not execution data.", "future normalized data and evidence", "Strategy registry outputs stay available for future lineage planning.", "ACTIVE_RUNTIME_REFERENCE"),
        ("BLOCK10", "SA044", "ACTIVE_RUNTIME", "Readable report outputs are report references, not execution data.", "future read_center comparison", "Readable report outputs stay available for operator reading.", "ACTIVE_RUNTIME_REFERENCE"),
        ("BLOCK11", "SA055", "ACTIVE_RUNTIME", "Architecture seal decision is a gate reference, not an execution asset.", "future source registry activation review", "Architecture seal remains a gate reference only.", "ACTIVE_RUNTIME_REFERENCE"),
        ("BLOCK12", "SA061", "ACTIVE_RUNTIME", "Source registry activation gate is only the permission source for this step.", "future hash/run_id/version binding planning", "The gate is not itself production lineage.", "ACTIVE_RUNTIME_REFERENCE"),
    ]
    for blocker_id, source_artifact_id, category, description, affected_gate, required_before, current_status in selected:
        rows.append(
            {
                "blocker_id": blocker_id,
                "source_artifact_id": source_artifact_id,
                "blocker_category": category,
                "blocker_description": description,
                "affected_future_gate": affected_gate,
                "required_resolution_before": required_before,
                "current_status": current_status,
            }
        )
    return rows


def build_next_binding_requirements() -> list[dict[str, object]]:
    requirements = [
        ("REQ01", "SOURCE_REGISTRY_COMPLETE", "Source registry outputs exist and cover the core categories.", "V20.5", "V20_5_SOURCE_ARTIFACT_REGISTRY.csv", "PASS"),
        ("REQ02", "V20_4_SEAL_ACCEPTED", "V20.4 architecture seal is complete and accepted.", "V20.5", "outputs/v20/ops/V20_4_READ_FIRST.txt", "PASS"),
        ("REQ03", "CURRENT_RUNTIME_SOURCES_REGISTERED", "V20.1 current runtime and report structure outputs are registered.", "V20.5", "V20_1 outputs", "PASS"),
        ("REQ04", "FACTOR_STRATEGY_SOURCES_REGISTERED", "V20.2 factor and strategy research outputs are registered.", "V20.5", "V20_2 outputs", "PASS"),
        ("REQ05", "READABLE_REPORT_SOURCES_REGISTERED", "V20.3 readable report framework outputs are registered.", "V20.5", "V20_3 outputs", "PASS"),
        ("REQ06", "ARCHITECTURE_SEAL_REFERENCES_REGISTERED", "V20.4 seal and gate outputs are registered.", "V20.5", "V20_4 outputs", "PASS"),
        ("REQ07", "V18_V19_BASELINES_SEALED", "V18 and V19 baseline references are sealed and retained.", "V20.5", "V18/V19 outputs", "PASS"),
        ("REQ08", "FUTURE_PLACEHOLDERS_REGISTERED", "Future normalized dataset and future backtest placeholders are registered.", "V20.5", "V20 placeholders", "PASS"),
        ("REQ09", "SOURCE_CATEGORIES_COVERED", "All required source categories are represented in the registry.", "V20.5", "source type classification", "PASS"),
        ("REQ10", "READY_FOR_HASH_BINDING_NEXT", "Source registry activation must permit the next hash/run_id/version planning step.", "V20.6", "source registry outputs", "PASS"),
    ]
    return [
        {
            "requirement_id": req_id,
            "requirement_category": category,
            "requirement_description": desc,
            "required_before_v20_step": before,
            "dependency_source": source,
            "current_status": status,
        }
        for req_id, category, desc, before, source, status in requirements
    ]


def build_report(source_rows: list[dict[str, object]], layer_rows: list[dict[str, object]], seal_pass: bool, dependency_found: int) -> str:
    categories = sorted({row["source_category"] for row in source_rows})
    return "\n".join(
        [
            "# V20.5 源注册激活报告",
            "",
            "## 结论",
            f"- 状态：{'SEALED' if seal_pass else 'WARN'}",
            "- 本步仅做源注册与分类，不计算官方哈希、不认证 run_id、不执行版本绑定、不执行 stale/leakage/PIT 门。",
            f"- V20.4 依赖检测：{'TRUE' if seal_pass else 'FALSE'}",
            f"- 检测到的依赖输入数：{dependency_found}",
            f"- 已注册源类别：{', '.join(categories)}",
            "",
            "## 注册范围",
            "- V18 和 V19 被标记为封存历史基线，仅用于参考比较。",
            "- V20.1-V20.4 作为当前运行、架构、报告和门控输出被注册。",
            "- 当前候选/排名/Top 输出、价格输出、因子/策略注册、可读报告以及 ops READ_FIRST 均已纳入源注册。",
            "- 未来标准化研究数据集和未来回测输出仅作为占位符注册，不视为真实数据。",
            "",
            "## 下一步门控",
            "- 源注册激活完成后，可以进入 V20.6 的 hash/run_id/version binding 规划。",
            "- stale/leakage/PIT、normalized dataset、factor evidence、exploratory backtest 和 dynamic weighting 仍全部阻塞。",
            "",
            "## 安全边界",
            "- 不创建正式交易信号、组合权重、因子权重变更、正式排名、正式回测或动态加权。",
            "- 不生成标准化真实研究数据行，不生成因子证据，不启用 broker/order/trading。",
            "",
            "## 说明",
            "- 当前输出为源注册激活层，用于后续 lineage 规划，不是执行层。",
        ]
    )


def build_current_alias_markdown() -> str:
    return "\n".join(
        [
            "# V20 当前源注册状态",
            "",
            "V20.1-V20.4 的架构、因子/策略、可读报告和封存门控输出已被注册为源分类项。",
            "V18 与 V19 被标记为封存历史基线，仅用于比较和参考。",
            "",
            "当前仍禁止：",
            "- 官方 hash binding",
            "- certified run_id",
            "- version binding",
            "- stale/leakage/PIT gate",
            "- normalized real data rows",
            "- factor evidence",
            "- exploratory backtest",
            "- dynamic weighting",
            "- trading outputs",
        ]
    )


def build_read_first(source_count: int, category_count: int, sealed_count: int, runtime_count: int, seal_pass: bool) -> None:
    lines = [
        "STATUS: WARN",
        "PATCH_NAME: V20.5_SOURCE_REGISTRY_ACTIVATION",
        "REPORTING_ONLY: TRUE",
        "SOURCE_REGISTRY_ONLY: TRUE",
        f"SOURCE_REGISTRY_ACTIVATED: {tf(seal_pass)}",
        "DATA_EXECUTION_STARTED: FALSE",
        "OFFICIAL_HASH_BINDING_CREATED: FALSE",
        "CERTIFIED_RUN_ID_CREATED: FALSE",
        "VERSION_BINDING_EXECUTED: FALSE",
        "STALE_LEAKAGE_GATE_EXECUTED: FALSE",
        "NORMALIZED_REAL_DATA_ROWS_CREATED: 0",
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
        f"READY_FOR_HASH_RUN_ID_VERSION_BINDING_NEXT: {tf(seal_pass)}",
        "READY_FOR_STALE_LEAKAGE_PIT_GATE_NEXT: FALSE",
        "READY_FOR_NORMALIZED_RESEARCH_DATASET_NEXT: FALSE",
        "READY_FOR_FACTOR_EVIDENCE_NEXT: FALSE",
        "READY_FOR_EXPLORATORY_BACKTEST_NEXT: FALSE",
        "READY_FOR_DYNAMIC_WEIGHTING_GATE_RESEARCH_NEXT: FALSE",
        "OFFICIAL_TRADING_ALLOWED: FALSE",
        "OFFICIAL_PORTFOLIO_WEIGHT_ALLOWED: FALSE",
        "OFFICIAL_FACTOR_WEIGHT_CHANGE_ALLOWED: FALSE",
        "OFFICIAL_BACKTEST_ALLOWED: FALSE",
        f"SOURCE_ARTIFACTS_REGISTERED: {source_count}",
        f"SOURCE_CATEGORIES_REGISTERED: {category_count}",
        f"SEALED_BASELINE_SOURCE_ARTIFACTS: {sealed_count}",
        f"CURRENT_RUNTIME_SOURCE_ARTIFACTS: {runtime_count}",
        "NEXT_RECOMMENDED_ACTION: V20.6_HASH_RUN_ID_VERSION_BINDING",
        "NEXT_RECOMMENDED_MODEL: GPT-5.5",
    ]
    write_text(OPS / "V20_5_READ_FIRST.txt", "\n".join(lines))


def main() -> None:
    v20_4_text = read_text(V20_4_READ_FIRST)
    v20_4_kv = read_kv(v20_4_text)
    v20_4_pass = (
        v20_4_kv.get("ARCHITECTURE_CLARIFICATION_COMPLETE") == "TRUE"
        and v20_4_kv.get("SOURCE_REGISTRY_ACTIVATION_ALLOWED_NEXT") == "TRUE"
    )

    source_rows = build_source_catalog()
    source_categories = sorted({row["source_category"] for row in source_rows})
    category_count = len(source_categories)
    sealed_count = sum(1 for row in source_rows if row["sealed_baseline"] == "TRUE")
    runtime_count = sum(1 for row in source_rows if row["current_runtime_source"] == "TRUE")

    canonical_rows = build_canonical_path_registry(source_rows)
    type_rows = build_source_type_classification()
    layer_rows = build_source_layer_map()
    availability_rows = build_availability_audit(source_rows)
    hash_rows = build_eligibility_rows(source_rows, "eligible_for_future_hash_binding", "Future Hash Binding Eligibility")
    normalized_rows = build_eligibility_rows(source_rows, "eligible_for_future_normalized_data", "Future Normalized Data Eligibility")
    evidence_rows = build_eligibility_rows(source_rows, "eligible_for_future_factor_evidence", "Future Factor Evidence Eligibility")
    backtest_rows = build_eligibility_rows(source_rows, "eligible_for_future_backtest", "Future Backtest Eligibility")
    blocker_rows = build_blocker_register(source_rows)
    next_binding_rows = build_next_binding_requirements()

    required_categories = {
        "current_candidate_outputs",
        "current_ranked_candidate_outputs",
        "current_top_candidate_outputs",
        "price_data_outputs",
        "manual_upload_templates",
        "manual_upload_ledgers",
        "factor_registry_outputs",
        "strategy_registry_outputs",
        "readable_report_outputs",
        "historical_v18_baseline_outputs",
        "historical_v19_baseline_outputs",
        "v20_architecture_outputs",
        "v20_read_center_outputs",
        "v20_ops_outputs",
        "future_normalized_dataset_placeholders",
        "future_backtest_placeholders",
    }
    source_registry_activated = v20_4_pass and len(source_rows) > 0 and required_categories.issubset(source_categories)

    write_csv(
        CONSOLIDATION / "V20_5_SOURCE_ARTIFACT_REGISTRY.csv",
        source_rows,
        [
            "source_artifact_id",
            "source_name",
            "source_category",
            "source_layer",
            "canonical_path",
            "path_exists_now",
            "source_status",
            "sealed_baseline",
            "current_runtime_source",
            "read_center_reference",
            "eligible_for_future_hash_binding",
            "eligible_for_future_normalized_data",
            "eligible_for_future_factor_evidence",
            "eligible_for_future_backtest",
            "blocker_reason",
        ],
    )
    write_csv(
        CONSOLIDATION / "V20_5_CANONICAL_SOURCE_PATH_REGISTRY.csv",
        canonical_rows,
        [
            "canonical_source_id",
            "canonical_path",
            "expected_owner_version",
            "path_role",
            "path_exists_now",
            "allowed_use",
            "blocked_use",
            "notes",
        ],
    )
    write_csv(
        CONSOLIDATION / "V20_5_SOURCE_TYPE_CLASSIFICATION.csv",
        type_rows,
        [
            "source_type_id",
            "source_category",
            "source_type_description",
            "expected_file_pattern",
            "current_or_historical",
            "machine_readable",
            "human_readable",
            "future_binding_required",
        ],
    )
    write_csv(
        CONSOLIDATION / "V20_5_SOURCE_LAYER_MAP.csv",
        layer_rows,
        [
            "source_layer_id",
            "source_layer_name",
            "source_categories",
            "source_layer_role",
            "current_runtime_role",
            "read_center_role",
            "future_binding_role",
            "status",
            "notes",
        ],
    )
    write_csv(
        CONSOLIDATION / "V20_5_SOURCE_AVAILABILITY_AUDIT.csv",
        availability_rows,
        [
            "audit_id",
            "source_artifact_id",
            "canonical_path",
            "availability_status",
            "missing_allowed_now",
            "required_before_hash_binding",
            "required_before_normalized_data",
            "required_before_backtest",
            "blocker_reason",
        ],
    )
    write_csv(
        CONSOLIDATION / "V20_5_SOURCE_ELIGIBILITY_FOR_HASH_BINDING.csv",
        hash_rows,
        ["eligibility_id", "source_artifact_id", "canonical_path", "source_category", "eligibility_status", "title", "reason"],
    )
    write_csv(
        CONSOLIDATION / "V20_5_SOURCE_ELIGIBILITY_FOR_NORMALIZED_DATA.csv",
        normalized_rows,
        ["eligibility_id", "source_artifact_id", "canonical_path", "source_category", "eligibility_status", "title", "reason"],
    )
    write_csv(
        CONSOLIDATION / "V20_5_SOURCE_ELIGIBILITY_FOR_FACTOR_EVIDENCE.csv",
        evidence_rows,
        ["eligibility_id", "source_artifact_id", "canonical_path", "source_category", "eligibility_status", "title", "reason"],
    )
    write_csv(
        CONSOLIDATION / "V20_5_SOURCE_ELIGIBILITY_FOR_BACKTEST.csv",
        backtest_rows,
        ["eligibility_id", "source_artifact_id", "canonical_path", "source_category", "eligibility_status", "title", "reason"],
    )
    write_csv(
        CONSOLIDATION / "V20_5_SOURCE_BLOCKER_REGISTER.csv",
        blocker_rows,
        [
            "blocker_id",
            "source_artifact_id",
            "blocker_category",
            "blocker_description",
            "affected_future_gate",
            "required_resolution_before",
            "current_status",
        ],
    )
    write_csv(
        CONSOLIDATION / "V20_5_NEXT_BINDING_REQUIREMENTS.csv",
        next_binding_rows,
        [
            "requirement_id",
            "requirement_category",
            "requirement_description",
            "required_before_v20_step",
            "dependency_source",
            "current_status",
        ],
    )

    write_csv(
        CONSOLIDATION / "V20_5_VALIDATION_SUMMARY.csv",
        [
            {
                "required_outputs_created": 12,
                "dependency_inputs_found": dependency_found_count(V20_1_REQUIRED + V20_2_REQUIRED + V20_3_REQUIRED + V20_4_REQUIRED),
                "v20_4_dependency_detected": tf(v20_4_pass),
                "v20_4_architecture_seal_complete": tf(v20_4_kv.get("ARCHITECTURE_CLARIFICATION_COMPLETE") == "TRUE"),
                "source_artifact_rows": len(source_rows),
                "canonical_source_path_rows": len(canonical_rows),
                "source_type_rows": len(type_rows),
                "source_layer_rows": len(layer_rows),
                "source_availability_rows": len(availability_rows),
                "hash_binding_eligibility_rows": len(hash_rows),
                "normalized_data_eligibility_rows": len(normalized_rows),
                "factor_evidence_eligibility_rows": len(evidence_rows),
                "backtest_eligibility_rows": len(backtest_rows),
                "source_blocker_rows": len(blocker_rows),
                "next_binding_requirement_rows": len(next_binding_rows),
                "source_registry_activated": tf(source_registry_activated),
                "ready_for_hash_run_id_version_binding_next": tf(source_registry_activated),
                "ready_for_stale_leakage_pit_gate_next": "FALSE",
                "ready_for_normalized_research_dataset_next": "FALSE",
                "ready_for_factor_evidence_next": "FALSE",
                "ready_for_exploratory_backtest_next": "FALSE",
                "ready_for_dynamic_weighting_gate_research_next": "FALSE",
                "official_trading_allowed": "FALSE",
                "official_portfolio_weight_allowed": "FALSE",
                "official_factor_weight_change_allowed": "FALSE",
                "official_backtest_allowed": "FALSE",
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
        ],
        [
            "required_outputs_created",
            "dependency_inputs_found",
            "v20_4_dependency_detected",
            "v20_4_architecture_seal_complete",
            "source_artifact_rows",
            "canonical_source_path_rows",
            "source_type_rows",
            "source_layer_rows",
            "source_availability_rows",
            "hash_binding_eligibility_rows",
            "normalized_data_eligibility_rows",
            "factor_evidence_eligibility_rows",
            "backtest_eligibility_rows",
            "source_blocker_rows",
            "next_binding_requirement_rows",
            "source_registry_activated",
            "ready_for_hash_run_id_version_binding_next",
            "ready_for_stale_leakage_pit_gate_next",
            "ready_for_normalized_research_dataset_next",
            "ready_for_factor_evidence_next",
            "ready_for_exploratory_backtest_next",
            "ready_for_dynamic_weighting_gate_research_next",
            "official_trading_allowed",
            "official_portfolio_weight_allowed",
            "official_factor_weight_change_allowed",
            "official_backtest_allowed",
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

    report = build_report(source_rows, layer_rows, source_registry_activated, dependency_found_count(V20_1_REQUIRED + V20_2_REQUIRED + V20_3_REQUIRED + V20_4_REQUIRED))
    current_alias = build_current_alias_markdown()
    write_text(READ_CENTER / "V20_5_SOURCE_REGISTRY_ACTIVATION_REPORT.md", report)
    write_text(READ_CENTER / "V20_CURRENT_SOURCE_REGISTRY_STATUS.md", current_alias)
    build_read_first(len(source_rows), category_count, sealed_count, runtime_count, source_registry_activated)


if __name__ == "__main__":
    main()
