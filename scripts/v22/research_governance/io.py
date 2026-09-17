"""Small JSON I/O and a future immutable-ledger normalization adapter."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .schemas import METRIC_FIELDS, TrialInput


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_immutable_manifest(ledger: Path, manifest: Path) -> dict[str, Any]:
    metadata = read_json(manifest)
    expected = str(
        metadata.get("ledger_sha256")
        or metadata.get("artifact_hashes", {}).get(ledger.name)
        or ""
    ).lower()
    if len(expected) != 64:
        raise ValueError("immutable manifest must contain ledger_sha256")
    observed = sha256_file(ledger)
    if observed != expected:
        raise ValueError("ledger hash does not match immutable manifest")
    explicit_immutable = metadata.get("status") in {"IMMUTABLE", "COMPLETE_IMMUTABLE"}
    overnight_frozen = all(metadata.get(name) is True for name in (
        "pre2026_research_complete", "pre2026_selection_complete", "pre2026_champion_frozen",
    )) and metadata.get("2026_outcome_read_count_at_freeze") == 0
    if not explicit_immutable and not overnight_frozen:
        raise ValueError("ledger manifest is not immutable")
    return metadata


def _decode_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if value is None or str(value).strip() == "":
        return {}
    decoded = json.loads(str(value))
    if not isinstance(decoded, dict):
        raise ValueError("ledger metric payload must be a JSON object")
    return decoded


def _metric_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    predictive = _decode_mapping(row.get("predictive_metrics"))
    economic = _decode_mapping(row.get("economic_metrics"))
    aliases = {
        "spearman_ic": "rank_ic",
        "ndcg_at_20": "ndcg_at_20",
        "ndcg20": "ndcg_at_20",
    }
    result = {name: row.get(name) for name in METRIC_FIELDS if row.get(name) is not None}
    for source, target in aliases.items():
        if source in predictive:
            result[target] = predictive[source]
    for name in METRIC_FIELDS:
        if name in economic:
            result[name] = economic[name]
    return result


class TrialLedgerAdapter:
    """Normalize completed OUTER_TEST rows without interpreting live state."""

    @staticmethod
    def normalize_rows(
        rows: Iterable[Mapping[str, Any]],
        metadata: Mapping[str, Any],
        benchmark: Mapping[str, Any],
    ) -> list[TrialInput]:
        eligible = [row for row in rows if (
            str(row.get("inner_fold", "")) in {"", "OUTER_TEST"}
            and str(row.get("status", "")).upper() in {"COMPLETE", "COMPLETED", "PASS"}
        )]
        grouped: dict[str, list[Mapping[str, Any]]] = {}
        for row in eligible:
            source_family = str(row.get("model_family") or "")
            grouped.setdefault(source_family, []).append(row)
        trials = []
        for source_family, group in sorted(grouped.items()):
            model_meta = dict(metadata.get("models", {}).get(source_family, {}))
            model_id = str(model_meta.get("model_id") or source_family)
            fold_metrics = model_meta.get("fold_metrics", {})
            folds = []
            for row in sorted(group, key=lambda item: str(item.get("outer_fold", ""))):
                fold_id = str(row.get("outer_fold") or "")
                folds.append({
                    "fold_id": fold_id,
                    "train_start": row.get("train_start"), "train_end": row.get("train_end"),
                    "validation_start": row.get("test_start") or row.get("validation_start"),
                    "validation_end": row.get("test_end") or row.get("validation_end"),
                    **_metric_payload(row),
                    **dict(fold_metrics.get(fold_id, {})),
                })
            payload = {
                "trial_id": f"JUDGE_{model_id}", "model_id": model_id,
                "model_family": model_meta.get("model_family", metadata.get("model_family", "ALPHA")),
                "feature_set_id": model_meta.get("feature_set_id"),
                "parameter_set_id": model_meta.get("parameter_set_id"),
                "benchmark_id": metadata.get("benchmark_id"), "training_cutoff": metadata.get("training_cutoff"),
                "universe_id": metadata.get("universe_id"), "data_lineage": metadata.get("data_lineage"),
                "pit_status": metadata.get("pit_status", "UNKNOWN"),
                "uses_2026_training": metadata.get("uses_2026_training", "UNKNOWN"),
                "uses_2026_parameter_search": metadata.get("uses_2026_parameter_search", "UNKNOWN"),
                "uses_2026_model_selection": metadata.get("uses_2026_model_selection", "UNKNOWN"),
                "research_run_id": metadata.get("research_run_id"), "folds": folds,
                "benchmark_folds": benchmark.get("folds", []),
                "economic_summary": model_meta.get("economic_summary", {}),
                "benchmark_summary": benchmark.get("economic_summary", {}),
            }
            trials.append(TrialInput.from_dict(payload))
        return trials

    @staticmethod
    def from_parquet(
        ledger: Path,
        metadata: Mapping[str, Any],
        benchmark: Mapping[str, Any],
        *,
        immutable_manifest: Path,
    ) -> list[TrialInput]:
        require_immutable_manifest(ledger, immutable_manifest)
        import pandas as pd  # Lazy: normal judge/tests require no dataframe dependency.

        frame = pd.read_parquet(ledger)
        return TrialLedgerAdapter.normalize_rows(frame.to_dict(orient="records"), metadata, benchmark)
