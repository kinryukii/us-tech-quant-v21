"""Typed, dependency-free schemas for Research Trial Judge R1."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


MODEL_FAMILIES = {"ALPHA", "RISK", "EXECUTION"}
METRIC_FIELDS = (
    "rank_ic",
    "ndcg_at_20",
    "return",
    "cagr",
    "sharpe",
    "sortino",
    "calmar",
    "max_drawdown",
    "turnover",
    "cost",
    "winner_capture",
    "winner_damage",
    "tail_loss",
)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "" or str(value).upper() in {"NA", "NAN", "NONE", "UNKNOWN"}:
        return None
    number = float(value)
    return number if number == number and abs(number) != float("inf") else None


@dataclass(frozen=True)
class FoldRecord:
    fold_id: str
    train_start: str | None = None
    train_end: str | None = None
    validation_start: str | None = None
    validation_end: str | None = None
    period_id: str | None = None
    metrics: Mapping[str, float | None] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "FoldRecord":
        metrics = {name: _optional_float(row.get(name)) for name in METRIC_FIELDS}
        return cls(
            fold_id=str(row.get("fold_id") or ""),
            train_start=_text_or_none(row.get("train_start")),
            train_end=_text_or_none(row.get("train_end")),
            validation_start=_text_or_none(row.get("validation_start")),
            validation_end=_text_or_none(row.get("validation_end")),
            period_id=_text_or_none(row.get("period_id")),
            metrics=metrics,
        )

    def metric(self, name: str) -> float | None:
        return self.metrics.get(name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fold_id": self.fold_id,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "validation_start": self.validation_start,
            "validation_end": self.validation_end,
            "period_id": self.period_id,
            **dict(self.metrics),
        }


def _text_or_none(value: Any) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    return str(value)


@dataclass(frozen=True)
class TrialInput:
    trial_id: str
    model_id: str
    model_family: str
    feature_set_id: str | None
    parameter_set_id: str | None
    benchmark_id: str | None
    training_cutoff: str | None
    universe_id: str | None
    data_lineage: str | None
    pit_status: str
    uses_2026_training: bool | str
    uses_2026_parameter_search: bool | str
    uses_2026_model_selection: bool | str
    folds: tuple[FoldRecord, ...]
    benchmark_folds: tuple[FoldRecord, ...] = ()
    economic_summary: Mapping[str, float | None] = field(default_factory=dict)
    benchmark_summary: Mapping[str, float | None] = field(default_factory=dict)
    research_run_id: str | None = None
    prospective_state: str = "UNKNOWN"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TrialInput":
        return cls(
            trial_id=str(payload.get("trial_id") or ""),
            model_id=str(payload.get("model_id") or ""),
            model_family=str(payload.get("model_family") or "").upper(),
            feature_set_id=_text_or_none(payload.get("feature_set_id")),
            parameter_set_id=_text_or_none(payload.get("parameter_set_id")),
            benchmark_id=_text_or_none(payload.get("benchmark_id")),
            training_cutoff=_text_or_none(payload.get("training_cutoff")),
            universe_id=_text_or_none(payload.get("universe_id")),
            data_lineage=_text_or_none(payload.get("data_lineage")),
            pit_status=str(payload.get("pit_status") or "UNKNOWN").upper(),
            uses_2026_training=payload.get("uses_2026_training", "UNKNOWN"),
            uses_2026_parameter_search=payload.get("uses_2026_parameter_search", "UNKNOWN"),
            uses_2026_model_selection=payload.get("uses_2026_model_selection", "UNKNOWN"),
            folds=tuple(FoldRecord.from_dict(row) for row in payload.get("folds", [])),
            benchmark_folds=tuple(FoldRecord.from_dict(row) for row in payload.get("benchmark_folds", [])),
            economic_summary=_metrics(payload.get("economic_summary", {})),
            benchmark_summary=_metrics(payload.get("benchmark_summary", {})),
            research_run_id=_text_or_none(payload.get("research_run_id")),
            prospective_state=str(payload.get("prospective_state") or "UNKNOWN").upper(),
        )


def _metrics(values: Mapping[str, Any]) -> dict[str, float | None]:
    return {name: _optional_float(values.get(name)) for name in METRIC_FIELDS}
