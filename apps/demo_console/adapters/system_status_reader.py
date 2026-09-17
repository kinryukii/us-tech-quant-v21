"""Evidence-scoped statuses; source availability never means a scientific PASS."""
import csv
import hashlib
import io
import json
import math
from pathlib import Path

from apps.demo_console.adapters.artifact_reader import ArtifactError, iso_date
from apps.demo_console.config.demo_config import (
    A_CONFIG_FINGERPRINT, A_SOURCE_FINGERPRINT, A_COEFFICIENT_FINGERPRINT,
    A_FEATURE_SCHEMA_FINGERPRINT,
    A2_CONFIG_FINGERPRINT, A2_SOURCE_FINGERPRINT, ALPHA_ID,
    ARTIFACT_PRODUCER_SHA256, BASELINE_ID, SOURCE_EXPERIMENT_ID, DemoConfig,
)
from apps.demo_console.models import PipelineStage, LearningProfile, ModelVintage


def learning_profile(manifest: dict) -> LearningProfile:
    """Project model metadata from read_freeze; no additional artifact access.

    Older/minimal fixtures may omit these optional metadata fields. A declared
    chronology must remain strictly pre-2026 and labels must mature before use.
    A manifest's chronology is a recorded claim, not a new leakage audit.
    """
    alpha = manifest.get("contracts", {}).get("A2", {})
    features = alpha.get("feature_schema", [])
    parameters = alpha.get("hyperparameters", {})
    if (not isinstance(features, list) or any(not isinstance(f, str) or not f for f in features)
            or len(features) != len(set(features)) or not isinstance(parameters, dict)
            or any(not isinstance(key, str) for key in parameters)):
        raise ArtifactError("MODEL_METADATA_SCHEMA_INVALID")
    parameter_items = []
    for key, value in sorted(parameters.items()):
        if not isinstance(key, str) or not isinstance(value, (str, int, float, bool, type(None))):
            raise ArtifactError("MODEL_PARAMETER_METADATA_INVALID")
        if isinstance(value, float) and not math.isfinite(value):
            raise ArtifactError("MODEL_PARAMETER_METADATA_INVALID")
        parameter_items.append((key, json.dumps(value, ensure_ascii=False, allow_nan=False)))
    vintages = []
    records = alpha.get("effective_model_vintages", [])
    required = {"year", "vintage", "train_max_date", "train_target_end_max", "prediction_min_date",
                "prediction_max_date", "training_row_count", "prediction_count"}
    if not isinstance(records, list):
        raise ArtifactError("MODEL_VINTAGE_SCHEMA_INVALID")
    for record in records:
        if (not isinstance(record, dict) or not required.issubset(record)
                or not isinstance(record["vintage"], str) or not record["vintage"]):
            raise ArtifactError("MODEL_VINTAGE_SCHEMA_INVALID")
        dates = [iso_date(record[key]) for key in (
            "train_max_date", "train_target_end_max", "prediction_min_date", "prediction_max_date")]
        if not dates[0] <= dates[1] < dates[2] <= dates[3] < "2026-01-01":
            raise ArtifactError("MODEL_VINTAGE_CHRONOLOGY_INVALID")
        year = record["year"]
        counts = [record[key] for key in ("training_row_count", "prediction_count")]
        if (type(year) is not int or str(year) != dates[2][:4] or str(year) != dates[3][:4]
                or any(type(value) is not int or value <= 0 for value in counts)):
            raise ArtifactError("MODEL_VINTAGE_COUNTS_INVALID")
        vintages.append(ModelVintage(year, str(record["vintage"]), *dates, *counts,
            str(record.get("effective_model_vintage_fingerprint") or ""),
            str(record.get("serialized_model_artifact_status") or "")))
    if len({v.year for v in vintages}) != len(vintages):
        raise ArtifactError("MODEL_VINTAGE_DUPLICATE_YEAR")
    target = alpha.get("target")
    if target is not None and not isinstance(target, str):
        raise ArtifactError("MODEL_TARGET_METADATA_INVALID")
    return LearningProfile(tuple(features), tuple(parameter_items), target,
                           tuple(sorted(vintages, key=lambda v: v.year)), alpha.get("source_fingerprint"))


def _verified_bytes(path, expected):
    with path.open("rb") as handle:
        data = handle.read()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ArtifactError("FREEZE_METADATA_IDENTITY_MISMATCH")
    return data


def _hash_rows(config):
    return list(csv.DictReader(io.StringIO(
        _verified_bytes(config.hash_manifest_path, config.hash_manifest_sha256).decode("utf-8-sig"))))


def _verify_artifact_binding(hashes, spec, artifact_id, category, role):
    matches = [row for row in hashes if row.get("artifact_id") == artifact_id]
    if len(matches) != 1:
        raise ArtifactError("FREEZE_ARTIFACT_ROLE_MISMATCH")
    row = matches[0]
    if (row.get("category") != category or row.get("role") != role
            or row.get("immutable") != "True"):
        raise ArtifactError("FREEZE_ARTIFACT_ROLE_MISMATCH")
    if (str(Path(row["absolute_path"]).resolve()) != str(spec.path.resolve())
            or row.get("sha256") != spec.sha256):
        raise ArtifactError("FREEZE_ARTIFACT_BINDING_MISMATCH")
    return row


def read_freeze(config: DemoConfig) -> dict:
    manifest = json.loads(_verified_bytes(config.manifest_path, config.manifest_sha256))
    hashes = _hash_rows(config)
    alpha = manifest.get("contracts", {}).get("A2", {})
    # The experiment also contains A1 and COMPARISON files. Bind the economic
    # arm and its frozen OOF identity, not merely a valid file under that root.
    if (manifest.get("schema") != "A_A2_CLEAN_BASELINE_FREEZE_MANIFEST_R1"
            or manifest.get("status") != "FROZEN_RESEARCH_BASELINE"
            or manifest.get("source_experiment") != SOURCE_EXPERIMENT_ID
            or manifest.get("frozen_baseline_name") != BASELINE_ID
            or manifest.get("immutability", {}).get("FROZEN_ALPHA_MODEL") != ALPHA_ID
            or alpha.get("model_family") != "HistGradientBoostingRegressor"
            or alpha.get("config_fingerprint") != A2_CONFIG_FINGERPRINT
            or alpha.get("source_fingerprint") != A2_SOURCE_FINGERPRINT
            or alpha.get("supplemental_full_pre2026_model", {}).get("used_for_frozen_oof_predictions") is not False):
        raise ArtifactError("FREEZE_IDENTITY_MISMATCH")
    if manifest.get("artifact_hash_manifest", {}).get("sha256") != config.hash_manifest_sha256:
        raise ArtifactError("FREEZE_HASH_CHAIN_MISMATCH")
    for spec, artifact_id, role in (
        (config.ranking, "a2_top20", "A2_top20_selections"),
        (config.positions, "a2_positions", "A2_position_ledger"),
        (config.daily, "a2_returns", "A2_portfolio_daily"),
    ):
        _verify_artifact_binding(hashes, spec, artifact_id, "A2_RESULT", role)
    producers = [row for row in hashes if row.get("artifact_id") == "experiment_adapter"]
    if (len(producers) != 1 or producers[0].get("category") != "SOURCE"
            or producers[0].get("role") != "a_a2_rebuild_adapter"
            or producers[0].get("immutable") != "True"
            or producers[0].get("relative_to_result_root", "").replace("\\", "/") != "scripts/run_rebuild.py"
            or producers[0].get("sha256") != ARTIFACT_PRODUCER_SHA256):
        raise ArtifactError("FREEZE_PRODUCER_BINDING_MISMATCH")
    # Expose the producer reference from the verified metadata, without loading
    # or executing that source file. This is adapter metadata, not a new freeze.
    return {**manifest, "artifact_producer_metadata": producers[0]}


def read_reference_binding(config: DemoConfig, manifest: dict) -> dict:
    """Verify the separate frozen A arm after the caller verifies the common freeze.

    This optional check never enters load_overview's required A2 identity path.
    A missing or invalid reference therefore cannot invalidate valid A2 evidence.
    """
    if config.reference_daily is None:
        raise ArtifactError("REFERENCE_NOT_CONFIGURED")
    contract = manifest.get("contracts", {}).get("A", {})
    if (contract.get("config_fingerprint") != A_CONFIG_FINGERPRINT
            or contract.get("source_fingerprint") != A_SOURCE_FINGERPRINT
            or contract.get("coefficient_fingerprint") != A_COEFFICIENT_FINGERPRINT
            or contract.get("feature_schema_fingerprint") != A_FEATURE_SCHEMA_FINGERPRINT
            or contract.get("coefficients_fixed") is not True
            or contract.get("portfolio_mapping") != "TOP20_EQUAL_WEIGHT_LONG_ONLY"
            or contract.get("score_direction") != "descending"
            or contract.get("ranking_tie_break") != "ticker deterministic"):
        raise ArtifactError("REFERENCE_CONTRACT_IDENTITY_MISMATCH")
    if manifest.get("artifact_hash_manifest", {}).get("sha256") != config.hash_manifest_sha256:
        raise ArtifactError("FREEZE_HASH_CHAIN_MISMATCH")
    evaluation = manifest.get("contracts", {}).get("evaluation", {})
    if any(evaluation.get(field) is not True for field in
           ("same_U_t", "same_cost_model", "same_portfolio_construction")):
        raise ArtifactError("REFERENCE_EVALUATION_CONTRACT_MISMATCH")
    return _verify_artifact_binding(_hash_rows(config), config.reference_daily,
                                    "a_returns", "A_RESULT", "A_portfolio_daily")


def pipeline_stages(manifest: dict, ranking_available: bool, portfolio_available: bool):
    pit = manifest.get("forensic_freeze", {}).get("temporal_causality")
    return (
        PipelineStage("Data / Source", "AVAILABLE", "Frozen baseline identity verified; historical research evidence."),
        PipelineStage("PIT / Eligibility", "AVAILABLE" if pit else "NOT_EXPOSED", f"Frozen audit reports temporal causality {pit or 'not exposed'}; no new PIT audit."),
        PipelineStage("Features", "NOT_EXPOSED", "Feature contract recorded; feature values are not loaded."),
        PipelineStage("A2 Ranking", "AVAILABLE" if ranking_available else "UNAVAILABLE", "Producer-supplied ranks and predictions in frozen Top20; full ranking not loaded."),
        PipelineStage("Top20", "AVAILABLE" if ranking_available else "UNAVAILABLE", "Exactly 20 unique producer-supplied ranks required."),
        PipelineStage("RX", "NOT_EXPOSED", "No authorized pre-2026 stateful RX decision trace in this baseline."),
        PipelineStage("Portfolio", "AVAILABLE" if portfolio_available else "UNAVAILABLE", "Raw A2 executed holdings only; combined RX final portfolio unavailable."),
        PipelineStage("Evidence", "PASS", "Exact baseline manifest, hash list and consumed artifact SHA-256 verified; integrity scope only."),
    )
