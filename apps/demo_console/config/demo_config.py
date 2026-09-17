"""Exact frozen input bindings; output paths use the canonical storage resolver."""
from dataclasses import dataclass
from pathlib import Path

from scripts.common.storage_paths import resolve


BASELINE_ID = "A_A2_QUARTERLY_13F_CLEAN_BASELINE_R1"
ALPHA_ID = "A2_QUARTERLY_13F_CLEAN_BASELINE_R1"
SOURCE_EXPERIMENT_ID = "A_VS_A2_QUARTERLY_13F_R1"
A2_CONFIG_FINGERPRINT = "871fbbc386d7678c744764f86e3beaaf5e74185c6e47a4157fdb7460ae577514"
A2_SOURCE_FINGERPRINT = "fd4fe78d27bfbf57c89343d60550366ccf7fcbf3d6a65e7ef66f28405d050c19"
ARTIFACT_PRODUCER_SHA256 = "68f4eb6599638db4c6af51b0ff8894f757b78a60dba27ce03e5c798e9508cc0e"
A_CONFIG_FINGERPRINT = "5cceee4ffe2a9f3400d2921b929115b785123815d00fbabcc011aec0787fc0e9"
A_SOURCE_FINGERPRINT = "1735939ed45e6ed08b124b4869875f56e1ebbb931337f611b25837dbfdbbc966"
A_COEFFICIENT_FINGERPRINT = "6a73f9da9ac91d9679fb7b058657e10be71e1da541d4ed009468611b018823bd"
A_FEATURE_SCHEMA_FINGERPRINT = "7ba4c7d26bace286d74b721e99fcd5c742f2601ca57996e2fb7027768954e45b"


@dataclass(frozen=True)
class ArtifactSpec:
    name: str
    path: Path
    sha256: str
    date_columns: tuple[str, ...]
    nullable_date_columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class DemoConfig:
    ranking: ArtifactSpec
    positions: ArtifactSpec
    daily: ArtifactSpec
    manifest_path: Path
    manifest_sha256: str
    hash_manifest_path: Path
    hash_manifest_sha256: str
    reference_daily: ArtifactSpec | None = None


def default_config() -> DemoConfig:
    root = resolve().results_root / "A_VS_A2_QUARTERLY_13F_R1"
    return DemoConfig(
        ranking=ArtifactSpec("Frozen Raw A2 Top20", root / "A2/top20_selections.parquet",
            "5e5203fdcd9a1e53fe1e2d64cd8c1adb78df4bd7acc733394d4dbd62392b8b20", ("signal_date",)),
        positions=ArtifactSpec("Frozen Raw A2 positions", root / "A2/position_ledger.parquet",
            "e75258d5450c4971cb6ec56ef0fb012718c121babda7a50dd3aac6b82654f1c3",
            ("date", "previous_date", "mark_source_date"), ("previous_date",)),
        daily=ArtifactSpec("Frozen Raw A2 execution metadata", root / "A2/portfolio_daily.parquet",
            "4e55f1a76952b864349dc058f1f42809f0792afd7060623c44c33c1a1cd45d73",
            ("execution_date",)),
        manifest_path=root / "audit/freeze_r1/frozen_baseline_manifest.json",
        manifest_sha256="398cff8076f8c761d87c12ce195ba98e9201209499caaaf7a14ae05ac1605125",
        hash_manifest_path=root / "audit/freeze_r1/frozen_artifact_hashes.csv",
        hash_manifest_sha256="84770018a4a4f095b476d2af433eedad0457a9e5904dfc6b7b13b905bc1dd10b",
        reference_daily=ArtifactSpec("Frozen A reference", root / "A/portfolio_daily.parquet",
            "f8af63c80ffb8cf204ba97030939004aee07b4257c4a12181d50aedb1eee14b0", ("execution_date",)),
    )
