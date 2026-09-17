"""Small synthetic fixtures, stored outside the repository and source artifacts."""
from __future__ import annotations

import hashlib
import csv
import json
import shutil
import warnings
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts.common.storage_paths import resolve_results_path


@pytest.fixture
def benchmark_stub(monkeypatch):
    """Keep UI tests away from real ETF prices; reader unit tests opt in separately."""
    from apps.demo_console.adapters import benchmarks_reader

    state = SimpleNamespace(calls=[], response=lambda dates, baseline_date: benchmarks_reader.BenchmarkHistory())

    def synthetic_benchmarks(dates, baseline_date=None):
        assert isinstance(dates, tuple)
        state.calls.append((dates, baseline_date))
        return state.response(dates, baseline_date)

    def forbidden(*args, **kwargs):
        raise AssertionError("UI tests must not read a real ETF configuration, manifest or price file")

    for name in ("default_benchmarks_config", "_read_manifest", "_read_prices"):
        monkeypatch.setattr(benchmarks_reader, name, forbidden)
    monkeypatch.setattr(benchmarks_reader, "read_benchmarks", synthetic_benchmarks)
    # Imported page aliases need the same protection when another fixture has
    # already loaded them in this Python process. No autouse patch hides the
    # real adapter from its own synthetic file-based contract tests.
    from apps.demo_console.pages import research
    from apps.demo_console.components import recorded_2026, system_overview
    for module in (research, recorded_2026, system_overview):
        monkeypatch.setattr(module, "read_benchmarks", synthetic_benchmarks, raising=False)
    return state


@pytest.fixture
def landing_without_performance(monkeypatch, benchmark_stub):
    """Existing non-performance AppTests must never reach a real landing reader."""
    from apps.demo_console.components import system_overview
    from apps.demo_console.models import PerformanceHistory

    calls = []

    def empty_synthetic_performance(end_date=None):
        calls.append(end_date)
        return PerformanceHistory(requested_end_date=end_date)

    monkeypatch.setattr(system_overview, "read_performance", empty_synthetic_performance)
    return calls


@pytest.fixture
def artifact_dir():
    root = resolve_results_path("demo-console", "cache")
    root.mkdir(parents=True, exist_ok=True)
    # mkdtemp's restrictive mode can make its own children inaccessible in the
    # managed Windows sandbox. Use an ordinary new directory; never repair ACLs.
    path = (root / f"test-{uuid4().hex}").resolve()
    path.mkdir()
    yield path
    # Only our explicitly created synthetic fixture directory is removable.
    if path.parent != root.resolve() or not path.name.startswith("test-"):
        raise AssertionError("Synthetic fixture cleanup escaped its assigned root")
    try:
        shutil.rmtree(path)
    except PermissionError as exc:
        warnings.warn(f"Preserved inaccessible task fixture: {path}: {exc}", RuntimeWarning)


@pytest.fixture
def make_artifact(artifact_dir):
    def create(rows, *, name="synthetic", date_columns=("decision_date",),
               statistics=True, schema=None, row_group_size=None):
        from apps.demo_console.config.demo_config import ArtifactSpec

        path = artifact_dir / f"{name}.parquet"
        table = pa.Table.from_pylist(rows, schema=schema)
        pq.write_table(table, path, write_statistics=statistics,
                       row_group_size=row_group_size)
        return ArtifactSpec(
            name=name, path=path,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            date_columns=tuple(date_columns),
        )
    return create


@pytest.fixture
def make_overview_config(make_artifact, artifact_dir):
    def create(*, optional=True):
        from apps.demo_console.config.demo_config import (
            A2_CONFIG_FINGERPRINT, A2_SOURCE_FINGERPRINT, ALPHA_ID,
            ARTIFACT_PRODUCER_SHA256, BASELINE_ID, SOURCE_EXPERIMENT_ID, DemoConfig,
        )

        ranking_rows = []
        for decision, first in (("2025-12-01", 1), ("2025-12-02", 2)):
            for rank, number in enumerate(range(first, first + 20), 1):
                row = {"signal_date": decision, "ticker": f"SYNTH_{number:02}", "a2_rank": rank}
                if optional:
                    row.update(a2_prediction=float(rank), universe_size=87)
                ranking_rows.append(row)
        ranking = make_artifact(ranking_rows, name="ranking", date_columns=("signal_date",))
        position_rows = []
        for execution, previous, first in (("2025-12-02", "2025-12-01", 1),
                                            ("2025-12-03", "2025-12-02", 2)):
            for number in range(1, first + 20):
                position_rows.append({
                    "date": execution, "previous_date": previous, "ticker": f"SYNTH_{number:02}",
                    "shares_before": 1.0 if first == 2 and number <= 20 else 0.0,
                    "shares_after": 1.0 if number >= first else 0.0,
                    "model": "A2_HGB", "portfolio": "TOP20_EQUAL_WEIGHT_LONG_ONLY",
                })
        positions = make_artifact(position_rows, name="positions", date_columns=("date", "previous_date"))
        daily_rows = []
        for execution in ("2025-12-02", "2025-12-03", "2025-12-04"):
            row = {"execution_date": execution, "model": "A2_HGB"}
            if optional:
                row.update(reconstructed_turnover=0.137, actual_risky_name_count=20)
            daily_rows.append(row)
        daily = make_artifact(daily_rows, name="daily", date_columns=("execution_date",))
        hash_path = artifact_dir / "synthetic_hashes.csv"
        with hash_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=[
                "artifact_id", "category", "role", "immutable",
                "absolute_path", "relative_to_result_root", "sha256",
            ])
            writer.writeheader()
            writer.writerows({"artifact_id": artifact_id, "category": "A2_RESULT",
                              "role": role, "immutable": "True",
                              "absolute_path": str(spec.path), "sha256": spec.sha256}
                             for spec, artifact_id, role in (
                                 (ranking, "a2_top20", "A2_top20_selections"),
                                 (positions, "a2_positions", "A2_position_ledger"),
                                 (daily, "a2_returns", "A2_portfolio_daily")))
            writer.writerow({"artifact_id": "experiment_adapter", "category": "SOURCE",
                             "role": "a_a2_rebuild_adapter", "immutable": "True",
                             "absolute_path": str(artifact_dir / "synthetic_producer.py"),
                             "relative_to_result_root": "scripts/run_rebuild.py",
                             "sha256": ARTIFACT_PRODUCER_SHA256})
        hash_sha = hashlib.sha256(hash_path.read_bytes()).hexdigest()
        manifest_path = artifact_dir / "synthetic_manifest.json"
        manifest_path.write_text(json.dumps({
            "schema": "A_A2_CLEAN_BASELINE_FREEZE_MANIFEST_R1",
            "status": "FROZEN_RESEARCH_BASELINE", "source_experiment": SOURCE_EXPERIMENT_ID,
            "artifact_hash_manifest": {"sha256": hash_sha}, "frozen_baseline_name": BASELINE_ID,
            "immutability": {"FROZEN_ALPHA_MODEL": ALPHA_ID},
            "forensic_freeze": {"temporal_causality": "SYNTHETIC_RECEIPT"},
            "contracts": {"A2": {
                "source_path": "synthetic_producer.py", "model_family": "HistGradientBoostingRegressor",
                "config_fingerprint": A2_CONFIG_FINGERPRINT,
                "source_fingerprint": A2_SOURCE_FINGERPRINT,
                "supplemental_full_pre2026_model": {"used_for_frozen_oof_predictions": False},
            }},
        }), encoding="utf-8")
        return DemoConfig(ranking, positions, daily, manifest_path,
                          hashlib.sha256(manifest_path.read_bytes()).hexdigest(), hash_path, hash_sha)
    return create
