"""Focused synthetic contract tests for the canonical research registry."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Iterator

import pytest

import prospective_research_lifecycle as lifecycle
import research_registry as rr


@pytest.fixture
def tmp_path() -> Iterator[Path]:
    """Sandbox-safe synthetic root; pytest's Windows 0700 basetemp is unreadable here."""
    base = Path(os.environ.get("US_TECH_QUANT_TEST_TMP_ROOT", r"D:\us-tech-quant-cache")).resolve()
    root = (base / f"pytest-research-registry-{uuid.uuid4().hex}").resolve()
    if root.parent != base or root.exists():
        raise RuntimeError(f"unsafe or pre-existing synthetic test root: {root}")
    root.mkdir()
    try:
        yield root
    finally:
        if root.parent != base:
            raise RuntimeError(f"refusing unsafe synthetic test cleanup: {root}")
        shutil.rmtree(root)


def fp(label: str) -> str:
    return rr.specification_fingerprint({"label": label})


def entity(
    entity_id: str,
    *,
    name: str | None = None,
    specification: str | None = None,
    information: str | None = None,
    mechanism: str = "rank",
    layer: str = "selection",
    status: str = "ACTIVE",
    aliases: list[str] | None = None,
    failures: int = 2,
    entity_type: str = "research_branch",
    minimum_manifest: str | None = None,
    **governance: object,
) -> dict[str, object]:
    row: dict[str, object] = {
        "entity_id": entity_id,
        "canonical_name": name or entity_id,
        "entity_type": entity_type,
        "status": status,
        "specification_fingerprint": fp(specification or f"spec:{entity_id}"),
        "information_source_fingerprint": fp(information or f"info:{entity_id}"),
        "mechanism_fingerprint": fp(f"mechanism:{mechanism}"),
        "decision_layer": layer,
        "evidence_source_temporal_status": "PIT_PRE_2026",
        "excluded_source_refs": ["synthetic://excluded"],
        "temporal_evidence_limitations": ["synthetic-only"],
        "factor_ledger_ref": "synthetic://factor-ledger",
        "trial_ledger_ref": "synthetic://trial-ledger",
        "trial_ledger_failure_row_count": failures,
        "post_2025_observation_count": 0,
        "minimum_system_manifest_ref": minimum_manifest,
        "authoritative_artifact_refs": [f"synthetic://authority/{entity_id.casefold()}"],
        "aliases": aliases or [],
    }
    row.update(governance)
    return row


def reviewed_patch(base: str, operations: list[dict[str, object]], **extra: object) -> dict[str, object]:
    patch: dict[str, object] = {
        "schema_version": 1,
        "expected_base_head_sha256": base,
        "author": "synthetic-author",
        "event_time_utc": "2025-12-31T00:00:00Z",
        "validation": {"status": "PASS", "post_2025_observation_count": 0},
        "independent_review": {"status": "PASS", "independent": True, "reviewer": "synthetic-reviewer"},
        "operations": operations,
        "operation_count": len(operations),
        "operations_sha256": rr.sha256_value(operations),
    }
    patch.update(extra)
    return patch


def audited_patch(base: str, operations: list[dict[str, object]]) -> dict[str, object]:
    patch = reviewed_patch(base, operations)
    patch.update(
        {
            "patch_purpose": "AUDITED_INVENTORY_BOOTSTRAP",
            "pinned_bootstrap_source_sha256": fp("synthetic-bootstrap-source"),
            "pinned_outcome_blind_inventory_sha256": fp("synthetic-outcome-blind-inventory"),
        }
    )
    return patch


def bootstrap(root: Path, *, status: str = "ACTIVE") -> tuple[dict[str, object], dict[str, object]]:
    raw = entity(
        "RAW_A2",
        name="Raw A2",
        specification="raw-a2-spec",
        information="raw-a2-source",
        mechanism="raw-score",
        aliases=["A2 Raw", "raw_a2", "Raw-A2"],
        status=status,
        information_family="canonical_raw_score",
        lifecycle_decision="retain",
    )
    result = rr.apply_patch(root, reviewed_patch(rr.GENESIS, [{"op": "add_entity", "entity": raw}]))
    return raw, result


def proposal_from(base: dict[str, object], entity_id: str, **changes: object) -> dict[str, object]:
    candidate = dict(base)
    candidate.update(
        {
            "entity_id": entity_id,
            "canonical_name": entity_id,
            "aliases": [],
            "specification_fingerprint": fp(f"spec:{entity_id}"),
            "authoritative_artifact_refs": [f"synthetic://authority/{entity_id.casefold()}"],
        }
    )
    candidate.update(changes)
    return {"candidate": candidate}


def test_01_raw_a2_canonical_and_aliases_resolve_same_id(tmp_path: Path) -> None:
    bootstrap(tmp_path)
    for value in ("Raw A2", "A2 Raw", "raw_a2", "Raw-A2"):
        assert rr.resolve_alias(tmp_path, value)["entity_id"] == "RAW_A2"
    assert rr.query_registry(tmp_path, alias="a2 raw")["entities"][0]["entity_id"] == "RAW_A2"


def test_02_exact_specification_fingerprint_is_blocked(tmp_path: Path) -> None:
    raw, _ = bootstrap(tmp_path)
    proposal = proposal_from(
        raw,
        "RAW_A2_COPY",
        specification_fingerprint=raw["specification_fingerprint"],
        information_source_fingerprint=fp("otherwise-distinct-source"),
    )
    assert rr.preflight_proposal(tmp_path, proposal)["decision"] == "BLOCKED_EXACT_DUPLICATE"


def test_03_exact_semantic_surface_is_functional_redundancy(tmp_path: Path) -> None:
    raw, _ = bootstrap(tmp_path)
    proposal = proposal_from(raw, "RAW_A2_MODEL")
    assert rr.preflight_proposal(tmp_path, proposal)["decision"] == "BLOCKED_FUNCTIONAL_REDUNDANCY"


@pytest.mark.parametrize(
    ("terminal_status", "change_type", "expected"),
    [
        ("CLOSED", "threshold", "BLOCKED_CLOSED_BRANCH"),
        ("TOMBSTONED", "rename", "BLOCKED_CLOSED_BRANCH"),
        ("SUPERSEDED", "repackaging", "BLOCKED_SUPERSEDED_BRANCH"),
    ],
)
def test_04_terminal_branch_repackaging_is_blocked(
    tmp_path: Path, terminal_status: str, change_type: str, expected: str
) -> None:
    raw, first = bootstrap(tmp_path)
    rr.apply_patch(
        tmp_path,
        reviewed_patch(
            first["head_sha256"],
            [{"op": "set_status", "entity_id": "RAW_A2", "status": terminal_status}],
        ),
    )
    proposal = proposal_from(raw, "RAW_A2_R2", parent_entity_id="RAW_A2")
    proposal.update({"parent_entity_id": "RAW_A2", "change_type": change_type})
    assert rr.preflight_proposal(tmp_path, proposal)["decision"] == expected


def test_05_distinct_information_source_is_not_falsely_blocked(tmp_path: Path) -> None:
    raw, _ = bootstrap(tmp_path)
    proposal = proposal_from(
        raw,
        "DISTINCT_SOURCE",
        information_source_fingerprint=fp("truly-new-source"),
        information_family="truly_distinct_family",
    )
    assert rr.preflight_proposal(tmp_path, proposal)["decision"] == "PASS_DISTINCT_INFORMATION_SOURCE"


def test_06_expected_base_head_mismatch_fails_closed(tmp_path: Path) -> None:
    bootstrap(tmp_path)
    with pytest.raises(rr.RegistryError, match="EXPECTED_BASE_HEAD_MISMATCH"):
        rr.apply_patch(
            tmp_path,
            reviewed_patch(rr.GENESIS, [{"op": "add_alias", "entity_id": "RAW_A2", "alias": "wrong-base"}]),
        )


def test_07_current_update_uses_atomic_same_directory_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Path, Path]] = []
    original = rr.os.replace

    def observed(source: str | Path, destination: str | Path) -> None:
        calls.append((Path(source), Path(destination)))
        original(source, destination)

    monkeypatch.setattr(rr.os, "replace", observed)
    _, applied = bootstrap(tmp_path)
    pointer = json.loads((tmp_path / rr.CURRENT_FILE).read_text(encoding="utf-8"))
    assert pointer == {
        "schema_version": 1,
        "head_sha256": applied["head_sha256"],
        "snapshot_id": applied["head_sha256"],
        "manifest_path": f"snapshots/{applied['head_sha256']}/manifest.json",
    }
    assert calls and calls[-1][1] == tmp_path / rr.CURRENT_FILE
    assert calls[-1][0].parent == calls[-1][1].parent
    assert not list(tmp_path.glob(".CURRENT.json.*.tmp"))
    assert not (tmp_path / "CURRENT").exists()


@pytest.mark.parametrize(
    ("field", "replacement", "error"),
    [
        ("schema_version", 2, "CURRENT_POINTER_SCHEMA_VERSION_INVALID"),
        ("snapshot_id", "0" * 64, "CURRENT_POINTER_SNAPSHOT_ID_MISMATCH"),
        ("manifest_path", "elsewhere/manifest.json", "CURRENT_POINTER_MANIFEST_PATH_INVALID"),
    ],
)
def test_current_json_tamper_fails_closed(
    tmp_path: Path, field: str, replacement: object, error: str
) -> None:
    bootstrap(tmp_path)
    pointer_path = tmp_path / rr.CURRENT_FILE
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer[field] = replacement
    pointer_path.write_text(json.dumps(pointer, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(rr.RegistryError, match=error):
        rr.current_state(tmp_path)


def test_08_new_snapshot_never_overwrites_old_snapshot(tmp_path: Path) -> None:
    _, first = bootstrap(tmp_path)
    old_dir = tmp_path / rr.SNAPSHOTS_DIR / first["head_sha256"]
    before = {path.name: path.read_bytes() for path in old_dir.iterdir()}
    second = rr.apply_patch(
        tmp_path,
        reviewed_patch(
            first["head_sha256"],
            [{"op": "update_entity", "entity": {"entity_id": "RAW_A2", "trial_ledger_failure_row_count": 3}}],
        ),
    )
    assert second["head_sha256"] != first["head_sha256"]
    assert before == {path.name: path.read_bytes() for path in old_dir.iterdir()}
    assert rr.diff_snapshots(tmp_path, first["head_sha256"], second["head_sha256"])["entities_changed"] == ["RAW_A2"]


def test_09_event_hash_tamper_is_detected(tmp_path: Path) -> None:
    bootstrap(tmp_path)
    path = tmp_path / rr.EVENTS_FILE
    row = json.loads(path.read_text(encoding="utf-8"))
    row["patch_sha256"] = "0" * 64
    path.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")
    validation = rr.validate_registry(tmp_path)
    assert validation["status"] == "FAIL"
    assert any("EVENT_HASH_MISMATCH" in error for error in validation["errors"])


@pytest.mark.parametrize("new_count", [1, None])
def test_10_trial_ledger_failure_count_cannot_decrease_or_become_unknown(
    tmp_path: Path, new_count: int | None
) -> None:
    _, first = bootstrap(tmp_path)
    with pytest.raises(rr.RegistryError, match="TRIAL_LEDGER_FAILURE_COUNT_REDUCED"):
        rr.apply_patch(
            tmp_path,
            reviewed_patch(
                first["head_sha256"],
                [{"op": "update_entity", "entity": {"entity_id": "RAW_A2", "trial_ledger_failure_row_count": new_count}}],
            ),
        )
    assert rr.current_state(tmp_path)["head_sha256"] == first["head_sha256"]


def test_trial_ledger_unknown_is_null_and_can_resolve_to_numeric(tmp_path: Path) -> None:
    unknown = entity(
        "UNKNOWN_TRIAL_LEDGER",
        information="unknown-ledger-source",
        trial_ledger_status="UNAVAILABLE_OR_NOT_IMPORTED_TEMPORAL_FIREWALL",
    )
    unknown["trial_ledger_ref"] = None
    unknown["trial_ledger_failure_row_count"] = None
    first = rr.apply_patch(
        tmp_path,
        reviewed_patch(rr.GENESIS, [{"op": "add_entity", "entity": unknown}]),
    )
    stored = rr.query_registry(tmp_path, entity_id="UNKNOWN_TRIAL_LEDGER")["entities"][0]
    assert stored["trial_ledger_failure_row_count"] is None
    assert stored["metadata"]["trial_ledger_status"] == "UNAVAILABLE_OR_NOT_IMPORTED_TEMPORAL_FIREWALL"

    second = rr.apply_patch(
        tmp_path,
        reviewed_patch(
            first["head_sha256"],
            [
                {
                    "op": "update_entity",
                    "entity": {
                        "entity_id": "UNKNOWN_TRIAL_LEDGER",
                        "trial_ledger_ref": "synthetic://resolved-trial-ledger",
                        "trial_ledger_failure_row_count": 4,
                    },
                }
            ],
        ),
    )
    assert second["status"] == "PASS"
    assert rr.query_registry(tmp_path, entity_id="UNKNOWN_TRIAL_LEDGER")["entities"][0]["trial_ledger_failure_row_count"] == 4


def test_trial_ledger_unknown_to_unknown_is_allowed(tmp_path: Path) -> None:
    unknown = entity("UNKNOWN_STAYS_UNKNOWN", information="unknown-stays-source")
    unknown["trial_ledger_ref"] = None
    unknown["trial_ledger_failure_row_count"] = None
    first = rr.apply_patch(
        tmp_path,
        reviewed_patch(rr.GENESIS, [{"op": "add_entity", "entity": unknown}]),
    )
    second = rr.apply_patch(
        tmp_path,
        reviewed_patch(
            first["head_sha256"],
            [{"op": "update_entity", "entity": {"entity_id": "UNKNOWN_STAYS_UNKNOWN", "reuse_decision": "PRESERVE_UNKNOWN"}}],
        ),
    )
    assert second["status"] == "PASS"
    assert rr.query_registry(tmp_path, entity_id="UNKNOWN_STAYS_UNKNOWN")["entities"][0]["trial_ledger_failure_row_count"] is None


def test_11_alias_conflict_is_detected(tmp_path: Path) -> None:
    first = entity("ONE", name="One", information="source-one", aliases=["Shared Alias"])
    second = entity("TWO", name="Two", information="source-two", aliases=["shared_alias"])
    with pytest.raises(rr.RegistryError, match="ALIAS"):
        rr.apply_patch(
            tmp_path,
            reviewed_patch(
                rr.GENESIS,
                [
                    {"op": "add_entity", "entity": first},
                    {"op": "add_entity", "entity": second},
                ],
            ),
        )
    assert rr.current_state(tmp_path)["head_sha256"] == rr.GENESIS


@pytest.mark.parametrize("surface", ["validation", "entity"])
def test_12_nonzero_post_2025_counter_blocks_apply(tmp_path: Path, surface: str) -> None:
    row = entity("POST_2025")
    if surface == "entity":
        row["post_2025_observation_count"] = 1
    patch = reviewed_patch(rr.GENESIS, [{"op": "add_entity", "entity": row}])
    if surface == "validation":
        patch["validation"] = {"status": "PASS", "post_2025_observation_count": 1}
    with pytest.raises(rr.RegistryError, match="POST_2025_COUNTER_NONZERO"):
        rr.apply_patch(tmp_path, patch)


@pytest.mark.parametrize(
    "metadata",
    [
        {"post_2025_observation_count": {"value": 1}},
        {"post_2025_observation_count": {"items": [{"value": 0}, {"value": 1}]}},
    ],
)
def test_nested_nonzero_post_2025_counter_context_is_not_lost(
    metadata: dict[str, object],
) -> None:
    with pytest.raises(rr.RegistryError, match="POST_2025_COUNTER_NONZERO"):
        rr._reject_outcome_fields({"validation": metadata})


def test_nested_counter_zero_and_unrelated_numeric_metadata_remain_allowed() -> None:
    rr._reject_outcome_fields({
        "validation": {
            "post_2025_observation_count": {"items": [{"value": 0}]},
            "schema": {"value": 3},
        },
    })


def test_13_snapshot_and_event_hashes_are_deterministic(tmp_path: Path) -> None:
    first_root = tmp_path / "one"
    second_root = tmp_path / "two"
    raw = entity("RAW_A2", name="Raw A2", information="source", aliases=["A2 Raw"])
    patch = reviewed_patch(rr.GENESIS, [{"op": "add_entity", "entity": raw}])
    first = rr.apply_patch(first_root, patch)
    second = rr.apply_patch(second_root, patch)
    assert first["head_sha256"] == second["head_sha256"]
    assert first["event"]["event_hash"] == second["event"]["event_hash"]
    for name in (rr.REGISTRY_FILE, rr.ALIASES_FILE, rr.MANIFEST_FILE, rr.VALIDATION_FILE):
        left = first_root / rr.SNAPSHOTS_DIR / first["head_sha256"] / name
        right = second_root / rr.SNAPSHOTS_DIR / second["head_sha256"] / name
        assert left.read_bytes() == right.read_bytes()


def test_14_exported_context_is_readable_by_simulated_task(tmp_path: Path) -> None:
    bootstrap(tmp_path)
    output = tmp_path / "task-context.json"
    result = rr.export_context(tmp_path, output, aliases_to_resolve=["A2 Raw"])
    simulated_task_context = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "PASS"
    assert simulated_task_context["entities"][0]["entity_id"] == "RAW_A2"
    assert simulated_task_context["entities"][0]["evidence_source_temporal_status"] == "PIT_PRE_2026"
    assert simulated_task_context["registry_head_sha256"] == rr.current_state(tmp_path)["head_sha256"]


def test_15_minimum_system_manifest_is_queryable(tmp_path: Path) -> None:
    manifest = entity(
        "MINIMUM_SYSTEM",
        name="Minimum System Manifest",
        information="minimum-system-source",
        mechanism="manifest",
        layer="system_manifest",
        entity_type="minimum_system_manifest",
        minimum_manifest="synthetic://minimum-system-manifest",
        authoritative_artifact_refs=["synthetic://control-plane"],
        reuse_decision="REUSE",
    )
    rr.apply_patch(tmp_path, reviewed_patch(rr.GENESIS, [{"op": "add_entity", "entity": manifest}]))
    result = rr.query_registry(tmp_path, filters={"entity_type": "minimum_system_manifest"})
    assert result["count"] == 1
    assert result["entities"][0]["minimum_system_manifest_ref"] == "synthetic://minimum-system-manifest"
    assert result["entities"][0]["metadata"]["reuse_decision"] == "REUSE"


def test_16_jsonl_patch_schema_and_cli_command_surface(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "registry"
    patch_path = tmp_path / "registry_patch.jsonl"
    bare_operation = {"op": "add_entity", "entity": entity("JSONL", information="jsonl-source")}
    header = reviewed_patch(rr.GENESIS, [bare_operation])
    header.pop("operations")
    header["record_type"] = "PATCH_HEADER"
    operation = {"record_type": "OPERATION", **bare_operation}
    patch_path.write_text(
        json.dumps(header, sort_keys=True) + "\n" + json.dumps(operation, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert rr.main(["--root", str(root), "apply-patch", "--patch", str(patch_path)]) == 0
    assert rr.main(["--root", str(root), "validate"]) == 0
    assert rr.main(["--root", str(root), "current"]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out


def test_review_and_metric_gates_fail_closed(tmp_path: Path) -> None:
    row = entity("GATED")
    bad_review = reviewed_patch(rr.GENESIS, [{"op": "add_entity", "entity": row}])
    bad_review["independent_review"] = {"status": "FAIL", "independent": True, "reviewer": "reviewer"}
    with pytest.raises(rr.RegistryError, match="INDEPENDENT_REVIEW_PASS_REQUIRED"):
        rr.apply_patch(tmp_path / "review", bad_review)
    metric_patch = reviewed_patch(rr.GENESIS, [{"op": "add_entity", "entity": row}])
    metric_patch["realized_holdout_sharpe"] = 1.0
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_FIELDS_FORBIDDEN"):
        rr.apply_patch(tmp_path / "metric", metric_patch)


@pytest.mark.parametrize(
    ("source_id", "change_type", "expected"),
    [
        ("CLOSED_IMPORT", "threshold", "BLOCKED_CLOSED_BRANCH"),
        ("TOMBSTONED_IMPORT", "rename", "BLOCKED_CLOSED_BRANCH"),
        ("SUPERSEDED_IMPORT", "model", "BLOCKED_SUPERSEDED_BRANCH"),
    ],
)
def test_audited_inventory_bootstrap_then_terminal_proposal_still_blocks(
    tmp_path: Path, source_id: str, change_type: str, expected: str
) -> None:
    rows = [
        entity(
            "SHARED_ONE",
            information="shared-source",
            mechanism="shared-mechanism",
            prior_lifecycle_status="OPEN_RESEARCH",
        ),
        entity(
            "SHARED_TWO",
            information="shared-source",
            mechanism="shared-mechanism",
            prior_lifecycle_status="ACTIVE_RESEARCH",
        ),
        entity(
            "CLOSED_IMPORT",
            information="closed-source",
            mechanism="closed-mechanism",
            status="CLOSED",
            prior_lifecycle_status="CLOSED_MECHANISM_UNRESOLVED",
        ),
        entity(
            "TOMBSTONED_IMPORT",
            information="tombstoned-source",
            mechanism="tombstoned-mechanism",
            status="TOMBSTONED",
            prior_lifecycle_status="TOMBSTONED_LEGACY",
        ),
        entity(
            "SUPERSEDED_IMPORT",
            information="superseded-source",
            mechanism="superseded-mechanism",
            status="SUPERSEDED",
            prior_lifecycle_status="SUPERSEDED_R1",
        ),
    ]
    patch = audited_patch(rr.GENESIS, [{"op": "add_entity", "entity": row} for row in rows])
    applied = rr.apply_patch(tmp_path, patch)
    assert applied["status"] == "PASS"
    for field in (
        "operation_count",
        "operations_sha256",
        "pinned_bootstrap_source_sha256",
        "pinned_outcome_blind_inventory_sha256",
    ):
        assert applied["manifest"][field] == patch[field]
    validation = json.loads(
        (
            tmp_path
            / rr.SNAPSHOTS_DIR
            / applied["head_sha256"]
            / rr.VALIDATION_FILE
        ).read_text(encoding="utf-8")
    )
    assert validation["operations_sha256"] == patch["operations_sha256"]
    assert validation["pinned_outcome_blind_inventory_sha256"] == patch["pinned_outcome_blind_inventory_sha256"]
    assert rr.query_registry(tmp_path, entity_id="CLOSED_IMPORT")["entities"][0]["metadata"]["prior_lifecycle_status"] == "CLOSED_MECHANISM_UNRESOLVED"
    source = next(row for row in rows if row["entity_id"] == source_id)
    proposal = proposal_from(source, f"{source_id}_R2", parent_entity_id=source_id)
    proposal.update({"parent_entity_id": source_id, "change_type": change_type})
    assert rr.preflight_proposal(tmp_path, proposal)["decision"] == expected


def test_audited_inventory_bootstrap_is_genesis_only(tmp_path: Path) -> None:
    _, first = bootstrap(tmp_path)
    patch = audited_patch(
        first["head_sha256"],
        [{"op": "add_entity", "entity": entity("LATE_IMPORT", information="late-source")}],
    )
    with pytest.raises(rr.RegistryError, match="AUDITED_INVENTORY_BOOTSTRAP_REQUIRES_GENESIS"):
        rr.apply_patch(tmp_path, patch)


@pytest.mark.parametrize(
    ("status", "candidate_name", "change_type", "expected"),
    [
        ("CLOSED", "Family Model R3", "model", "BLOCKED_CLOSED_BRANCH"),
        ("TOMBSTONED", "Family Threshold R7", "threshold", "BLOCKED_CLOSED_BRANCH"),
        ("SUPERSEDED", "Family Retry R12", "", "BLOCKED_SUPERSEDED_BRANCH"),
    ],
)
def test_terminal_same_family_variant_blocks_even_with_new_fingerprints_and_no_parent(
    tmp_path: Path, status: str, candidate_name: str, change_type: str, expected: str
) -> None:
    terminal = entity(
        "TERMINAL_FAMILY",
        name="Original Family Branch",
        information="old-fingerprint",
        mechanism="old-mechanism",
        layer="old-layer",
        status=status,
        information_family="normalized family",
    )
    bootstrap_patch = audited_patch(rr.GENESIS, [{"op": "add_entity", "entity": terminal}])
    rr.apply_patch(tmp_path, bootstrap_patch)
    candidate = entity(
        "FAMILY_VARIANT",
        name=candidate_name,
        information="spoofed-new-fingerprint",
        mechanism="changed-mechanism",
        layer="changed-layer",
        information_family="Normalized-Family",
    )
    proposal: dict[str, object] = {"candidate": candidate}
    if change_type:
        proposal["change_type"] = change_type
    assert rr.preflight_proposal(tmp_path, proposal)["decision"] == expected


def test_new_source_and_new_family_remains_distinct_after_terminal_import(tmp_path: Path) -> None:
    terminal = entity(
        "OLD_FAMILY",
        information="old-source",
        status="CLOSED",
        information_family="old-family",
    )
    patch = audited_patch(rr.GENESIS, [{"op": "add_entity", "entity": terminal}])
    rr.apply_patch(tmp_path, patch)
    candidate = entity(
        "NEW_FAMILY",
        name="New Model R3",
        information="genuinely-new-source",
        information_family="genuinely-new-family",
    )
    assert rr.preflight_proposal(tmp_path, {"candidate": candidate})["decision"] == "PASS_DISTINCT_INFORMATION_SOURCE"


@pytest.mark.parametrize(
    "metric_key",
    [
        "nav",
        "alpha",
        "ic",
        "rank_ic",
        "auroc",
        "auc",
        "ap",
        "f1",
        "precision",
        "recall",
        "accuracy",
        "calibration",
        "win_rate_20d",
        "hit_rate",
        "realized_label_count",
        "tail_event_status",
        "classification_report",
        "returns",
        "return_value",
        "pnl",
        "sharpe",
        "maximum_drawdown",
        "mcc",
        "specificity",
        "sensitivity",
        "true_positive_rate",
        "false_positive_rate",
        "confusion_matrix",
        "roc_curve",
        "pr_curve",
        "brier_score",
        "log_loss",
        "cross_entropy",
        "rmse",
        "mse",
        "mae",
        "r_squared",
        "r2",
        "lift",
        "gini",
        "ks_statistic",
    ],
)
def test_recursive_metric_key_firewall_covers_task_families(
    tmp_path: Path, metric_key: str
) -> None:
    candidate = entity("METRIC_FIREWALL", information="metric-firewall-source")
    candidate["governance_metadata"] = {"nested": {metric_key: 0}}
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_FIELDS_FORBIDDEN"):
        rr.preflight_proposal(tmp_path, {"candidate": candidate})


@pytest.mark.parametrize(
    "metric_key",
    [
        "outcome_derived_metadata",
        "prior_outcome_derived_metadata_status",
        "p_and_l",
        "daily_p_and_l_value",
        "net_asset_value",
        "portfolio_net_asset_value_status",
        "area_under_roc_curve",
        "validation_area_under_roc_curve_value",
    ],
)
def test_recursive_metric_key_firewall_rejects_normalized_synonyms(
    tmp_path: Path, metric_key: str
) -> None:
    candidate = entity("METRIC_SYNONYM", information="metric-synonym-source")
    candidate["governance_metadata"] = {"nested": {metric_key: None}}
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_FIELDS_FORBIDDEN"):
        rr.preflight_proposal(tmp_path, {"candidate": candidate})


@pytest.mark.parametrize(
    "metric_text",
    [
        "2026 AUROC=0.61",
        "holdout Sharpe 1.2",
        "rank IC: -0.03",
        "R2 = 0.17",
        "MCC 0.44",
        "false positive rate 7%",
        "log loss: 0.52",
        "holdout AUROC was poor",
        "holdout AUROC was sixty one percent",
        "20 day forward return = 5%",
        "20 day forward return was five percent",
    ],
)
def test_recursive_firewall_rejects_metric_values_hidden_in_free_text(
    tmp_path: Path, metric_text: str
) -> None:
    candidate = entity("FREE_TEXT_METRIC", information="free-text-metric-source")
    candidate["governance_metadata"] = {"nested": {"neutral_note": metric_text}}
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_VALUES_FORBIDDEN"):
        rr.preflight_proposal(tmp_path, {"candidate": candidate})


def test_metric_name_governance_statement_without_value_is_allowed(tmp_path: Path) -> None:
    candidate = entity(
        "NO_METRIC_VALUE",
        information="no-metric-value-source",
        governance_note="No realized AUROC or Sharpe values are stored; evidence is unavailable.",
    )
    assert rr.preflight_proposal(tmp_path, {"candidate": candidate})["decision"] == "PASS_DISTINCT_INFORMATION_SOURCE"


def test_overlay_registration_metadata_round_trips_without_performance_fields() -> None:
    registration = {
        "namespace": "OVERLAY",
        "frozen_name": "RANGE_EXHAUSTION_SCORE_MARGIN_OVERLAY_R1",
        "short_name": "RX_MARGIN_R1",
        "prospective_shadow_only": True,
        "canonical_promotion": False,
        "production_authorization": False,
    }
    normalized = rr._normalize_entity(entity(
        "RX_MARGIN_RANGE_EXHAUSTION_LINEAGE",
        entity_type="RESEARCH_OVERLAY",
        **registration,
    ))

    restored = rr._entity_from_storage(rr._entity_to_storage(normalized))

    for key, expected in registration.items():
        assert restored["metadata"][key] == expected
        assert type(restored["metadata"][key]) is type(expected)
    assert rr._performance_field_paths(restored["metadata"]) == []
    assert rr._performance_value_paths(restored["metadata"]) == []


@pytest.mark.parametrize(
    "forbidden_key",
    [
        "realized_returns",
        "prospective_economic_outcomes",
        "sharpe",
        "alpha",
        "cagr",
        "mdd",
        "maxdd",
        "economic_performance_conclusion",
    ],
)
def test_overlay_registration_rejects_forbidden_economic_metadata_fields(
    forbidden_key: str,
) -> None:
    raw = entity(
        "RX_MARGIN_RANGE_EXHAUSTION_LINEAGE",
        entity_type="RESEARCH_OVERLAY",
        namespace="OVERLAY",
        frozen_name="RANGE_EXHAUSTION_SCORE_MARGIN_OVERLAY_R1",
        short_name="RX_MARGIN_R1",
        prospective_shadow_only=True,
        canonical_promotion=False,
        production_authorization=False,
    )
    raw[forbidden_key] = None

    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_FIELDS_FORBIDDEN"):
        rr._normalize_entity(raw)


@pytest.mark.parametrize(
    "variant",
    [
        "sharpe_ratio",
        "sharpeRatio",
        "SharpeRatio",
        "Sharpe Ratio",
        "Sharpe-Ratio",
    ],
)
def test_economic_metric_key_normalization_handles_common_encodings(
    variant: str,
) -> None:
    assert rr._normalized_key(variant) == "sharpe_ratio"
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_FIELDS_FORBIDDEN"):
        rr._reject_outcome_fields({variant: 1.2})


@pytest.mark.parametrize(
    ("metric_key", "value"),
    [
        ("Sharpe12Pct", 1.2),
        ("CAGR40pct", 0.4),
    ],
)
def test_metric_to_digit_boundary_cannot_hide_economic_field(
    metric_key: str, value: float
) -> None:
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_FIELDS_FORBIDDEN"):
        rr._reject_outcome_fields({metric_key: value})


@pytest.mark.parametrize(
    "economic_text",
    ["Sharpe12Pct", "Sharpe12Percent", "CAGR40pct"],
)
def test_metric_to_digit_boundary_cannot_hide_economic_value(
    economic_text: str,
) -> None:
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_VALUES_FORBIDDEN"):
        rr._reject_outcome_fields({"notes": economic_text})


def test_performance_boundary_normalization_preserves_compact_metric_codes() -> None:
    assert rr._normalized_performance_key("R2") == "r2"
    assert rr._normalized_performance_key("F1") == "f1"
    assert rr._normalized_performance_key("r2Score") == "r2_score"
    assert rr._normalized_performance_key("f1Score") == "f1_score"
    assert rr._normalized_performance_key("R212Pct") == "r2_12_pct"
    assert rr._normalized_performance_key("F140Percent") == "f1_40_percent"


@pytest.mark.parametrize(
    "qualified_metric",
    [
        "R212Pct",
        "r212pct",
        "R240Percent",
        "r240percent",
        "F112Pct",
        "f112pct",
        "F140Percent",
        "f140percent",
    ],
)
def test_compact_metric_code_digit_qualification_is_rejected_across_surfaces(
    qualified_metric: str,
) -> None:
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_FIELDS_FORBIDDEN"):
        rr._reject_outcome_fields({qualified_metric: 1.2})
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_VALUES_FORBIDDEN"):
        rr._reject_outcome_fields({"notes": qualified_metric})
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_VALUES_FORBIDDEN"):
        rr._reject_outcome_fields(
            {"artifact_ref": f"synthetic://registry/{qualified_metric}"}
        )
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_VALUES_FORBIDDEN"):
        rr._reject_outcome_fields(
            {
                "artifact_ref": (
                    "synthetic://registry/item"
                    f"?metric={qualified_metric}&value=stored"
                )
            }
        )


def test_f1_prefixed_sha256_remains_a_structural_fingerprint() -> None:
    opaque_sha256 = "f1" + "a" * 62
    normalized = rr._normalize_entity(
        entity("OPAQUE_HASH_ENTITY", mechanism_fingerprint=opaque_sha256)
    )
    assert normalized["mechanism_fingerprint"] == opaque_sha256


@pytest.mark.parametrize(
    "qualified_identity",
    [
        "f1" + "a" * 62 + "-exceptional",
        "f1abcdef-1234-4abc-8def-1234567890ab-exceptional",
    ],
)
def test_opaque_identity_plus_qualification_is_not_exempt(
    qualified_identity: str,
) -> None:
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_VALUES_FORBIDDEN"):
        rr._reject_outcome_fields({"notes": qualified_identity})


def test_exact_uuid_remains_a_structural_identity() -> None:
    rr._reject_outcome_fields(
        {"identity_ref": "f1abcdef-1234-4abc-8def-1234567890ab"}
    )


def test_entire_short_hex_reference_segment_remains_opaque() -> None:
    rr._reject_outcome_fields(
        {"artifact_ref": "synthetic://registry/f1abcdef"}
    )


@pytest.mark.parametrize(
    "qualified_reference",
    [
        "synthetic://registry/f1abcdef-exceptional",
        "synthetic://registry/item?metric=f1abcdef&value=exceptional",
    ],
)
def test_short_hex_reference_qualification_is_not_exempt(
    qualified_reference: str,
) -> None:
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_VALUES_FORBIDDEN"):
        rr._reject_outcome_fields({"artifact_ref": qualified_reference})


@pytest.mark.parametrize(
    "economic_metadata",
    [
        {"sharpeRatio": 1.2},
        {"SharpeRatio": 1.2},
        {"P&L": -3.0},
        {"P/L": -3.0},
        {"realizedPnL": 1.2},
        {"PnLValue": 1.2},
        {"dailyMaxDD": -0.25},
        {"label": "Sharpe", "value": 1.2},
        {"label": ["Sharpe"], "value": 1.2},
        {"label": "dailyPnL", "value": 1.2},
        {"metric": "maxDrawdown", "value": -0.25},
        {"metrics": [{"name": "CAGR", "value": 0.40}]},
        {
            "identity": {"namespace": "OVERLAY"},
            "provenance": {
                "artifact_ref": "synthetic://rx/artifact",
                "nested": {"fieldName": "realizedPerformance", "result": 1.1},
            },
        },
    ],
)
def test_overlay_registration_rejects_semantic_economic_metric_encodings(
    economic_metadata: dict[str, object],
) -> None:
    raw = entity(
        "RX_MARGIN_RANGE_EXHAUSTION_LINEAGE",
        entity_type="RESEARCH_OVERLAY",
        namespace="OVERLAY",
        frozen_name="RANGE_EXHAUSTION_SCORE_MARGIN_OVERLAY_R1",
        short_name="RX_MARGIN_R1",
        prospective_shadow_only=True,
        canonical_promotion=False,
        production_authorization=False,
        governance_metadata=economic_metadata,
    )

    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_FIELDS_FORBIDDEN"):
        rr._normalize_entity(raw)


@pytest.mark.parametrize(
    "metadata",
    [
        {"label": "Sharpe", "wrapper": {"value": 1.2}},
        {"metric": "maxDrawdown", "payload": {"result": {"value": -0.25}}},
        {"name": "CAGR", "items": [{"value": 0.40}]},
        {"name": "CAGR", "items": [0.40]},
        {"label": "Sharpe", "wrapper": {"payload": [1.2]}},
    ],
)
def test_metric_descriptor_context_survives_transparent_nested_containers(
    metadata: dict[str, object],
) -> None:
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_FIELDS_FORBIDDEN"):
        rr._reject_outcome_fields(metadata)


@pytest.mark.parametrize(
    "metadata",
    [
        {"label": "Sharpe", "wrapper": {"payload": ["exceptional"]}},
        {"label": "Sharpe", "wrapper": {"payload": ["1.2"]}},
        {"metric": "maxDrawdown", "wrapper": {"payload": ["25pct"]}},
        {"name": "CAGR", "data": [{"nested": {"payload": "40%"}}]},
        {"label": "alpha", "wrapper": {"payload": ["positive"]}},
        {
            "wrapper": {
                "label": "Sharpe",
                "data": [{"nested": {"payload": "outstanding"}}],
            }
        },
    ],
)
def test_metric_descriptor_context_survives_transparent_textual_leaves(
    metadata: dict[str, object],
) -> None:
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_FIELDS_FORBIDDEN"):
        rr._reject_outcome_fields(metadata)


def test_descriptor_text_propagation_does_not_ban_neutral_text_globally() -> None:
    rr._reject_outcome_fields({
        "label": "Sharpe",
        "wrapper": {"payload": ["not stored", "a" * 64]},
    })
    rr._reject_outcome_fields({
        "label": "schemaVersion",
        "wrapper": {"payload": ["exceptional", "1.2"]},
    })


def test_neutral_descriptor_and_unassociated_numeric_scalars_remain_allowed() -> None:
    rr._reject_outcome_fields({"label": "schemaVersion", "wrapper": {"value": 1.2}})
    rr._reject_outcome_fields({"wrapper": {"value": 1.2}, "retry_count": 3})
    rr._reject_outcome_fields({"name": "schemaVersion", "items": [0.40]})
    rr._reject_outcome_fields({"wrapper": {"payload": [1.2]}})


def test_overlay_registration_accepts_legitimate_numeric_governance_metadata() -> None:
    contract_sha256 = fp("rx-frozen-contract")
    artifact_sha256 = fp("rx-registration-artifact")
    raw = entity(
        "RX_MARGIN_RANGE_EXHAUSTION_LINEAGE",
        entity_type="RESEARCH_OVERLAY",
        namespace="OVERLAY",
        frozen_name="RANGE_EXHAUSTION_SCORE_MARGIN_OVERLAY_R1",
        short_name="RX_MARGIN_R1",
        prospective_shadow_only=True,
        canonical_promotion=False,
        production_authorization=False,
        governance_metadata={
            "identity": {
                "namespace": "OVERLAY",
                "frozenName": "RANGE_EXHAUSTION_SCORE_MARGIN_OVERLAY_R1",
                "shortName": "RX_MARGIN_R1",
            },
            "provenance": {
                "schemaVersion": 1,
                "contractSha256": contract_sha256,
                "artifactSha256": artifact_sha256,
                "artifactReference": "synthetic://rx/registration",
            },
            "lifecycleState": "REGISTERED_NOT_STARTED",
            "prospectiveShadowOnly": True,
            "canonicalPromotion": False,
            "productionAuthorization": False,
        },
    )

    normalized = rr._normalize_entity(raw)
    metadata = normalized["metadata"]["governance_metadata"]

    assert metadata["provenance"]["schemaVersion"] == 1
    assert metadata["provenance"]["contractSha256"] == contract_sha256
    assert metadata["provenance"]["artifactSha256"] == artifact_sha256
    assert metadata["lifecycleState"] == "REGISTERED_NOT_STARTED"
    assert metadata["prospectiveShadowOnly"] is True
    assert metadata["canonicalPromotion"] is False
    assert metadata["productionAuthorization"] is False
    assert rr._performance_field_paths(metadata) == []
    assert rr._performance_value_paths(metadata) == []


@pytest.mark.parametrize(
    "economic_text",
    [
        "holdout sharpeRatio = 1.2",
        "holdout sharpe_ratio = 1.2",
        "holdout maxDrawdown = -0.25",
        "realizedPnL = 12",
        "Realized performance was strong.",
        "Economic performance was weak.",
        "Sharpe.Ratio = 1.2",
        "Sharpe, 1.2",
        "P-and-L = 12",
        "P.and.L = 12",
        "economic.outcome was strong",
    ],
)
def test_recursive_value_firewall_rejects_normalized_economic_text(
    economic_text: str,
) -> None:
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_VALUES_FORBIDDEN"):
        rr._reject_outcome_fields({"notes": {"review": economic_text}})


@pytest.mark.parametrize(
    "economic_text",
    [
        "Sharpe was exceptional.",
        "Sharpe is outstanding.",
        "Sharpe remained favorable.",
        "Sharpe ranked first.",
        "Sharpe proved remarkable.",
        "Sharpe: exceptional.",
        "Exceptional Sharpe.",
        "Sharpe—outstanding.",
    ],
)
def test_recursive_value_firewall_rejects_structural_economic_conclusions(
    economic_text: str,
) -> None:
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_VALUES_FORBIDDEN"):
        rr._reject_outcome_fields({"notes": economic_text})


@pytest.mark.parametrize("field", ["artifact_ref", "canonical_name", "entity_id"])
def test_identity_or_reference_field_cannot_hide_economic_conclusion(
    field: str,
) -> None:
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_VALUES_FORBIDDEN"):
        rr._reject_outcome_fields({field: "Sharpe: exceptional"})


def test_opaque_metric_like_identity_and_reference_remain_allowed() -> None:
    rr._reject_outcome_fields({
        "entity_id": "RAW_A2_R2",
        "canonical_name": "Bar Mechanism R2",
        "artifact_ref": "synthetic://registry/SHARPE_ARTIFACT",
    })
    rr._reject_outcome_fields({
        "entity_id": "BAR_VERSION_R2",
        "canonical_name": "Bar Version R2",
        "artifact_ref": "synthetic://registry/BAR_VERSION_R2",
    })
    rr._reject_outcome_fields({
        "entity_id": "BAR12_R2",
        "canonical_name": "Bar12 Version R2",
        "artifact_ref": "synthetic://registry/BAR12_R2",
    })


@pytest.mark.parametrize(
    "reference",
    [
        "synthetic://registry/item?sharpe=exceptional",
        "synthetic://registry/item?SharpeRatio=1.2",
        "synthetic://registry/Sharpe12Pct",
        "synthetic://registry/CAGR40pct",
        "synthetic://registry/maxDrawdown25pct",
        "synthetic://registry/item?metric=Sharpe12Pct&value=stored",
        "synthetic://registry/%2553harpe%253D1.2",
        "synthetic://registry/item#sharpe:exceptional",
        "synthetic://registry/BAR_EXCEPTIONAL_R2",
        "synthetic://registry/BarExceptional_R2",
        "synthetic://registry/BAR_FORTY_PERCENT_R2",
        "synthetic://registry/BAR12pct_R2",
        "synthetic://registry/Bar12Pct_R2",
        "synthetic://registry/f1abcdef-1234-4abc-8def-1234567890ab-exceptional",
        (
            "synthetic://registry/f1abcdef-1234-4abc-8def-1234567890ab"
            "?metric=Sharpe&value=exceptional"
        ),
        "synthetic://registry/SHARPE_ARTIFACT?value=1.2",
        "synthetic://registry/sharpe/artifact?value=1.2",
        "synthetic://registry/MAX_DRAWDOWN_ARTIFACT?value=-0.25",
        "synthetic://sharpe.registry/artifact?value=1.2",
        "synthetic://registry/value/1.2?metric=Sharpe",
        "synthetic://registry/SHARPE_ARTIFACT#value=1.2",
        "synthetic://registry/item?value=1.2#metric=Sharpe",
        "synthetic://registry/sharpe/1.2",
        "synthetic://registry/SHARPE_ARTIFACT/value/1.2",
        "synthetic://registry/sharpe/artifact/result/1.2",
        "synthetic://registry/sharpe/artifact/score/12",
        "synthetic://registry/SHARPE_ARTIFACT/exceptional",
        "synthetic://registry/SHARPE_ARTIFACT/40pct",
        "synthetic://registry/sharpe-exceptional.json",
        "synthetic://registry/sharpe/exceptional",
        "notes/sharpe-exceptional",
        "notes/sharpe-exceptional1",
        "notes/maxDrawdown-25pct",
        "synthetic://registry/item?label=Sharpe&value=exceptional",
        "artifact://x/result?metric=CAGR&value=40pct",
        "synthetic://sharpe:exceptional@registry/item",
    ],
)
def test_reference_shape_cannot_hide_economic_qualification(reference: str) -> None:
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_VALUES_FORBIDDEN"):
        rr._reject_outcome_fields({
            "provenance": {"artifact_refs": [reference]},
        })


@pytest.mark.parametrize(
    "reference",
    [
        "synthetic://registry/SHARPE_ARTIFACT",
        "synthetic://registry/sharpe/artifact",
        "synthetic://registry/item#sharpe-artifact",
        "D:/contracts/SHARPE_ARTIFACT.json",
        "artifact://registry/" + "a" * 64,
        "D:/evidence/contracts/frozen_contract.json",
        "synthetic://registry/%2552AW_A2_R2",
        "synthetic://registry/f1abcdef-1234-4abc-8def-1234567890ab",
        "synthetic://registry/SHARPE_ARTIFACT?version=1.2",
        "synthetic://registry/sharpe/artifact?version=1.2",
        "synthetic://registry/MAX_DRAWDOWN_ARTIFACT?version=1.2",
        "synthetic://registry/SHARPE_ARTIFACT/version/1.2",
        "synthetic://registry/sharpe/artifact/v/1.2",
        "synthetic://registry/SHARPE_ARTIFACT/schema/2",
        "synthetic://registry/SHARPE_ARTIFACT/build/123",
        "synthetic://registry/SHARPE_ARTIFACT/revision/4",
        "synthetic://registry/SHARPE_ARTIFACT/2024/",
        "synthetic://registry/SHARPE_ARTIFACT/part/2",
        "synthetic://registry/SHARPE_ARTIFACT/partition/12",
        "synthetic://registry/SHARPE_ARTIFACT/2024/09/01",
        "synthetic://registry/SHARPE_ARTIFACT/v1.2",
        "synthetic://registry/sharpe/artifact/v1.2",
    ],
)
def test_neutral_metric_like_opaque_references_remain_allowed(reference: str) -> None:
    rr._reject_outcome_fields({"artifact_refs": [reference]})


@pytest.mark.parametrize(
    "reference",
    [
        "artifact://x/sharpe/" + "a" * 64 + "/1.2",
        "artifact://x/sharpe/12345678-1234-4abc-8def-1234567890ab/1.2",
        "artifact://x/maxDrawdown/" + "a" * 64 + "/25pct",
        "artifact://x/CAGR/12345678-1234-4abc-8def-1234567890ab/40pct",
        "artifact://x/sharpe/" + "a" * 40 + "/1.2",
        "artifact://x/sharpe/" + "a" * 64 + "/./1.2",
        "artifact://x/sharpe/" + "a" * 64 + "/../1.2",
        "artifact://sharpe/" + "a" * 64 + "/1.2",
        "artifact://x/" + "a" * 64 + "/1.2?metric=Sharpe",
        "sharpe://x/" + "a" * 64 + "/1.2",
        "maxdrawdown://x/" + "a" * 64 + "/25pct",
        "cagr://x/12345678-1234-4abc-8def-1234567890ab/40pct",
        "artifact://sharpe@x/" + "a" * 64 + "/1.2",
    ],
)
def test_opaque_identity_separator_does_not_reset_metric_context(reference: str) -> None:
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_VALUES_FORBIDDEN"):
        rr._reject_outcome_fields({"artifact_ref": reference})


@pytest.mark.parametrize(
    "reference",
    [
        "artifact://x/item?metric=Sharpe&data=1.2",
        "artifact://x/item?metric=Sharpe&data=1e2",
        "artifact://x/item?metric=Sharpe&data=25bps",
        "artifact://x/item?data=1.2&metric=Sharpe",
        "artifact://x/item?metric=Sharpe&payload=1.2",
        "artifact://x/item?label=Sharpe&x=exceptional",
        "artifact://x/item?metric=CAGR&payload=40pct",
        "artifact://x/item?label=Sharpe&wrapper=1.2",
        "artifact://x/item#metric=Sharpe&data=1.2",
        (
            "artifact://x/item?metric=Sharpe&payload="
            + "a" * 64
            + "&data=1.2"
        ),
        (
            "artifact://x/item?payload=40pct&opaque="
            + "a" * 64
            + "&metric=CAGR"
        ),
        (
            "artifact://x/item?metric=maxDrawdown&token="
            "12345678-1234-4abc-8def-1234567890ab&payload=25pct"
        ),
    ],
)
def test_query_semantic_unit_preserves_descriptor_context(
    reference: str,
) -> None:
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_VALUES_FORBIDDEN"):
        rr._reject_outcome_fields({"artifact_ref": reference})


def test_query_semantic_unit_allows_only_neutral_identity_and_version_values() -> None:
    rr._reject_outcome_fields({
        "artifact_ref": (
            "artifact://x/item?metric=Sharpe&artifact_sha256="
            + "a" * 64
            + "&version=1.2"
        )
    })
    rr._reject_outcome_fields({
        "artifact_ref": "artifact://x/item?data=1.2",
    })


@pytest.mark.parametrize(
    "reference",
    [
        "artifact://x/item/" + "a" * 64 + "/1.2",
        "artifact://x/item/12345678-1234-4abc-8def-1234567890ab/1.2",
        "artifact://x/sharpe/" + "a" * 64 + "/version/1.2",
        "artifact://sharpe/" + "a" * 64 + "/version/1.2",
        "artifact://x/version/1.2?metric=Sharpe",
    ],
)
def test_neutral_opaque_separator_references_remain_allowed(reference: str) -> None:
    rr._reject_outcome_fields({"artifact_ref": reference})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("entity_id", "R2_EXCEPTIONAL"),
        ("entity_id", "BAR_EXCEPTIONAL_R2"),
        ("entity_id", "BAR_FORTY_PERCENT_R2"),
        ("entity_id", "BAR12pct_R2"),
        ("canonical_name", "R2: exceptional"),
        ("canonical_name", "BarExceptional_R2"),
        ("canonical_name", "BarFortyPercent_R2"),
        ("canonical_name", "Bar12Pct_R2"),
        ("canonical_name", "exceptional R2"),
        ("canonical_name", "Bar exceptional R2"),
        ("canonical_name", "Bar Mechanism R2 exceptional"),
    ],
)
def test_r2_version_identity_cannot_bypass_economic_qualification(
    field: str, value: str
) -> None:
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_VALUES_FORBIDDEN"):
        rr._reject_outcome_fields({field: value})


@pytest.mark.parametrize("version", ["R2", "r2", "V2", "v2", "R2.1", "R22", "V22"])
def test_exact_full_field_identity_version_remains_structural(version: str) -> None:
    rr._reject_outcome_fields({"canonical_name": version})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("entity_id", "A2_COST_NAV_REPLAY_ENGINE"),
        ("entity_id", "A2_ALPHA_SIGNAL_ENGINE"),
        ("entity_id", "SHARPE2025"),
        ("canonical_name", "A2_COST_NAV_REPLAY_ENGINE"),
        ("entity_type", "ALPHA_COMPONENT"),
    ],
)
def test_strict_full_field_structural_identity_is_allowed(
    field: str, value: str,
) -> None:
    rr._reject_outcome_fields({field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("entity_id", "A2_COST_NAV_REPLAY_ENGINE_EXCEPTIONAL"),
        ("entity_id", "SHARPE_EXCEPTIONAL"),
        ("entity_id", "SHARPE_1P2"),
        ("entity_id", "SHARPE_0P8"),
        ("entity_id", "SHARPE_MINUS_1P2"),
        ("entity_id", "SHARPE_PLUS_1P2"),
        ("entity_id", "CAGR_40PCT"),
        ("entity_id", "CAGR_1e2"),
        ("entity_id", "SHARPE_1E_2"),
        ("entity_id", "SHARPE_1E_MINUS_2"),
        ("entity_id", "SHARPE_25BPS"),
        ("entity_id", "MDD_25_PERCENT"),
        ("entity_id", "MAX_DRAWDOWN_25PCT"),
        ("entity_id", "ALPHA_PLUS_50BP"),
        ("entity_id", "ALPHA_MINUS_25BPS"),
        ("entity_id", "RETURN_12P5PCT"),
        ("entity_id", "PNL_PLUS_100BP"),
        ("entity_id", "ALPHA_POSITIVE"),
        ("entity_id", "SHARPE. POSITIVE"),
        ("entity_id", "CAGR. 40PCT"),
        ("entity_id", "ALPHA. PLUS_50BP"),
        ("entity_id", "SHARPE_1EMINUS2"),
        ("entity_id", "SHARPE_1EPLUS2"),
        ("entity_id", "SHARPEEXCEPTIONAL"),
        ("entity_id", "ALPHAPOSITIVE"),
        ("entity_id", "ALPHAPLUS50BP"),
        ("entity_id", "PNLPLUS100BP"),
        ("entity_id", "SHARPE12"),
        ("entity_id", "CAGR40"),
        ("entity_id", "MDD25"),
        ("entity_id", "ALPHA50"),
        ("entity_id", "RETURN12"),
        ("entity_id", "PNL100"),
        ("canonical_name", "SHARPE_1P2"),
        ("canonical_name", "SHARPE. 1P2"),
        ("component_id", "SHARPE. 1P2"),
        ("model_id", "SHARPE; POSITIVE"),
        ("arbitrary_identity", "CAGR. 40PCT"),
        ("canonical_name", "A2_COST_NAV_REPLAY_ENGINE_1.2"),
        ("canonical_name", "sharpe-1.2"),
        ("entity_type", "ALPHA_COMPONENT_POSITIVE"),
    ],
)
def test_structural_identity_exemption_rejects_outcome_qualification(
    field: str, value: str,
) -> None:
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_VALUES_FORBIDDEN"):
        rr._reject_outcome_fields({field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("entity_id", "SHARPE_1P2"),
        ("entity_id", "SHARPE_0P8"),
        ("entity_id", "SHARPE_MINUS_1P2"),
        ("entity_id", "SHARPE_PLUS_1P2"),
        ("entity_id", "SHARPE_1E2"),
        ("entity_id", "SHARPE_1E_2"),
        ("entity_id", "SHARPE_1E_MINUS_2"),
        ("entity_id", "CAGR_40PCT"),
        ("entity_id", "CAGR_40_PERCENT"),
        ("entity_id", "MDD_25PCT"),
        ("entity_id", "MAX_DRAWDOWN_25PCT"),
        ("entity_id", "ALPHA_PLUS_50BP"),
        ("entity_id", "ALPHA_MINUS_25BPS"),
        ("entity_id", "RETURN_12P5PCT"),
        ("entity_id", "PNL_PLUS_100BP"),
        ("entity_id", "SHARPE. POSITIVE"),
        ("entity_id", "CAGR. 40PCT"),
        ("entity_id", "ALPHA. PLUS_50BP"),
        ("entity_id", "SHARPE_1EMINUS2"),
        ("entity_id", "SHARPE_1EPLUS2"),
        ("entity_id", "SHARPEEXCEPTIONAL"),
        ("entity_id", "ALPHAPOSITIVE"),
        ("entity_id", "ALPHAPLUS50BP"),
        ("entity_id", "PNLPLUS100BP"),
        ("entity_id", "SHARPE12"),
        ("entity_id", "CAGR40"),
        ("entity_id", "MDD25"),
        ("entity_id", "ALPHA50"),
        ("entity_id", "RETURN12"),
        ("entity_id", "PNL100"),
        ("canonical_name", "SHARPE_1P2"),
        ("canonical_name", "SHARPE. 1P2"),
        ("component_id", "SHARPE. 1P2"),
        ("model_id", "SHARPE; POSITIVE"),
        ("arbitrary_identity", "CAGR. 40PCT"),
    ],
)
def test_complete_entity_rejects_encoded_performance_identity(
    field: str, value: str,
) -> None:
    candidate = entity(
        "A2_SAFE_STRUCTURAL_COMPONENT",
        name="A2_SAFE_STRUCTURAL_COMPONENT",
    )
    candidate[field] = value

    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_VALUES_FORBIDDEN"):
        rr._normalize_entity(candidate)


@pytest.mark.parametrize(
    "reference",
    [
        "SHARPE_1P2",
        "SHARPE. 1P2",
        "SHARPE; POSITIVE",
        "CAGR. 40PCT",
        "ALPHA. PLUS_50BP",
        "SHARPE_1EMINUS2",
        "SHARPE_1EPLUS2",
        "SHARPEEXCEPTIONAL",
        "ALPHAPOSITIVE",
        "ALPHAPLUS50BP",
        "PNLPLUS100BP",
        "SHARPE12",
        "CAGR40",
        "MDD25",
        "ALPHA50",
        "RETURN12",
        "PNL100",
        "artifact://x/SHARPE_1P2",
        "artifact://x/sharpe/1P2",
        "artifact://x/item?metric=Sharpe&data=1P2",
        "artifact://x/item?payload=1P2&metric=Sharpe",
    ],
)
def test_reference_identity_exemption_rejects_encoded_performance_value(
    reference: str,
) -> None:
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_VALUES_FORBIDDEN"):
        rr._reject_outcome_fields({"artifact_ref": reference})


def test_existing_structural_registry_row_remains_consumable() -> None:
    raw = entity(
        "A2_COST_NAV_REPLAY_ENGINE",
        entity_type="ALPHA_COMPONENT",
        excluded_source_refs=[
            "D:/us-tech-quant-results/A2_ALGORITHM_R2A_2026_FORWARD/contract.json",
        ],
        authoritative_artifact_refs=[
            "D:/us-tech-quant-results/A2_RISK_OS_R2/risk_os_r2_final_summary.json",
        ],
        lifecycle_reason=(
            "Required identity, PIT, replay, or forward-control infrastructure; "
            "not a separate alpha claim."
        ),
        economic_role="INCREMENTAL_ALPHA",
        information_family="PIT state rank sector and corrected return labels",
        information_source="PIT state rank sector and corrected return labels",
        model_family="Identity and recall diagnostic only; no fitted model",
        portfolio_action="No policy and no strategy return",
        outcome_horizon="Existing forward-return windows",
        parent_entity_ids=["A2_COST_NAV_REPLAY_ENGINE"],
    )

    normalized = rr._normalize_entity(raw)
    restored = rr._entity_from_storage(rr._entity_to_storage(normalized))

    assert restored["entity_id"] == "A2_COST_NAV_REPLAY_ENGINE"
    assert restored["metadata"]["lifecycle_reason"].endswith("alpha claim.")


def test_configured_authoritative_registry_is_consumable_read_only() -> None:
    repo = Path(rr.__file__).resolve().parent
    config = json.loads((repo / "config" / "research_registry.json").read_text(encoding="utf-8"))
    configured_root = Path(str(config["registry_root"]))
    if not configured_root.is_absolute():
        configured_root = (repo / configured_root).resolve()
    if not configured_root.is_dir():
        pytest.skip("configured authoritative registry is unavailable")

    state = rr.current_state(configured_root)
    query = rr.query_registry(configured_root)
    lifecycle_registry = lifecycle._registry_module(repo)
    lifecycle_root = lifecycle._registry_root(repo)
    lifecycle_query = lifecycle_registry.query_registry(lifecycle_root)

    assert state["status"] == "PASS"
    assert query["status"] == "PASS"
    assert lifecycle_query["status"] == "PASS"
    assert query["head_sha256"] == lifecycle_query["head_sha256"]


def test_realized_performance_governance_denial_without_value_remains_allowed() -> None:
    metadata = {
        "governance_note": (
            "No realized performance or Sharpe values are stored; evidence is unavailable."
        ),
        "schemaVersion": 2,
    }

    rr._reject_outcome_fields(metadata)
    assert rr._performance_field_paths(metadata) == []
    assert rr._performance_value_paths(metadata) == []


@pytest.mark.parametrize(
    "economic_text",
    [
        "No Sharpe value of 1.2 is stored.",
        "No realized performance of 25% is recorded.",
        "No Sharpe result of twelve percent is retained.",
        "No Sharpe result was excellent and stored.",
        "No Sharpe = 1.2 is persisted.",
        "No copy of the Sharpe result, rated exceptional, is stored.",
    ],
)
def test_storage_denial_cannot_hide_embedded_economic_value(
    economic_text: str,
) -> None:
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_VALUES_FORBIDDEN"):
        rr._reject_outcome_fields({"notes": economic_text})


@pytest.mark.parametrize(
    "mixed_text",
    [
        "No Sharpe values are stored; realized performance was positive.",
        "No Sharpe values are stored; realized performance beat the benchmark.",
        "No Sharpe values are stored and realized performance was positive.",
        "No tests failed, realized performance outperformed the benchmark.",
        "No files were changed because realized performance exceeded its benchmark.",
        "No Sharpe values are stored or realized performance was excellent.",
        "No Sharpe values are stored because realized performance was excellent.",
        "No Sharpe values are stored despite realized performance exceeded its benchmark.",
    ],
)
def test_governance_denial_cannot_suppress_separate_economic_conclusion(
    mixed_text: str,
) -> None:
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_VALUES_FORBIDDEN"):
        rr._reject_outcome_fields({"notes": mixed_text})


def test_prospective_economic_conclusion_text_is_rejected_but_denial_is_allowed() -> None:
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_VALUES_FORBIDDEN"):
        rr._reject_outcome_fields({"notes": "Prospective economic outcome was strong."})

    rr._reject_outcome_fields({
        "governance_note": "No prospective economic outcomes are stored."
    })


def test_structural_forward_target_identity_is_not_a_realized_metric(tmp_path: Path) -> None:
    candidate = entity(
        "FORWARD_TARGET_IDENTITY",
        information="forward-target-identity-source",
        target_definition="20 day forward return",
    )
    assert rr.preflight_proposal(tmp_path, {"candidate": candidate})["decision"] == "PASS_DISTINCT_INFORMATION_SOURCE"


@pytest.mark.parametrize(
    ("field", "structural_text"),
    [
        (
            "prior_negative_evidence",
            "Pre-2026 trials tested the branch; alpha loss was the closure rationale.",
        ),
        (
            "economic_thesis",
            "Winner-label recall/rank 40 identifies the intended candidate set.",
        ),
        (
            "economic_thesis",
            "Five-session MAE defines the target geometry for this mechanism.",
        ),
        (
            "target_definition",
            "20 day forward return greater than or equal to 5 percent",
        ),
        (
            "winner_target_definition",
            "Rank 40 within the fixed winner-label target definition.",
        ),
        (
            "tail_target_definition",
            "Five day forward return below negative 10 percent defines the tail target.",
        ),
        (
            "target_definition",
            "Realized top-1-percent or Q90 upper-tail event on mean 3D 5D 10D 20D excess return",
        ),
    ],
)
def test_entity_normalization_allows_structural_inventory_evidence(
    field: str, structural_text: str
) -> None:
    raw = entity(
        f"STRUCTURAL_{field.upper()}",
        information=f"structural-source:{field}",
        **{field: structural_text},
    )
    normalized = rr._normalize_entity(raw)
    assert normalized["metadata"][field] == structural_text


def test_safe_structural_field_still_rejects_realized_holdout_result() -> None:
    raw = entity(
        "STRUCTURAL_FIELD_LEAK",
        information="structural-field-leak-source",
        economic_thesis="Holdout AUROC was 0.61.",
    )
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_VALUES_FORBIDDEN"):
        rr._normalize_entity(raw)


def test_target_definition_rejects_appended_metric_assignment_value() -> None:
    for value in (
        "20 day forward return = 5%",
        "20 day forward return five percent",
    ):
        with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_VALUES_FORBIDDEN"):
            rr._reject_outcome_fields({"target_definition": value})


@pytest.mark.parametrize("control_key", ["similarity_score", "similarity_threshold", "equivalence_score", "equivalence_threshold"])
def test_similarity_numeric_control_keys_are_rejected(tmp_path: Path, control_key: str) -> None:
    candidate = entity("NO_SIMILARITY_CONTROL", information="no-similarity-source")
    with pytest.raises(rr.RegistryError, match="SIMILARITY_SCORE_OR_THRESHOLD_FORBIDDEN"):
        rr.preflight_proposal(tmp_path, {"candidate": candidate, control_key: 0.9})
    patch = reviewed_patch(rr.GENESIS, [{"op": "add_entity", "entity": candidate}])
    patch[control_key] = 0.9
    with pytest.raises(rr.RegistryError, match="SIMILARITY_SCORE_OR_THRESHOLD_FORBIDDEN"):
        rr.apply_patch(tmp_path, patch)


def test_negative_similarity_threshold_creation_attestation_is_not_a_control(tmp_path: Path) -> None:
    candidate = entity(
        "NO_NEW_SIMILARITY_THRESHOLD",
        information="no-new-similarity-threshold-source",
        new_similarity_threshold_created=False,
    )
    assert rr.preflight_proposal(tmp_path, {"candidate": candidate})["decision"] == "PASS_DISTINCT_INFORMATION_SOURCE"


def test_same_family_or_source_exact_surface_blocks_without_numeric_similarity(tmp_path: Path) -> None:
    raw, _ = bootstrap(tmp_path)
    same_family = proposal_from(
        raw,
        "SAME_FAMILY_NEW_SOURCE",
        information_source_fingerprint=fp("spoofed-new-source"),
    )
    assert rr.preflight_proposal(tmp_path, same_family)["decision"] == "BLOCKED_FUNCTIONAL_REDUNDANCY"
    same_source = proposal_from(
        raw,
        "SAME_SOURCE_NEW_FAMILY",
        information_family="renamed-family",
    )
    assert rr.preflight_proposal(tmp_path, same_source)["decision"] == "BLOCKED_FUNCTIONAL_REDUNDANCY"


def test_same_family_changed_surface_requires_review(tmp_path: Path) -> None:
    raw, _ = bootstrap(tmp_path)
    proposal = proposal_from(
        raw,
        "SAME_FAMILY_CHANGED_SURFACE",
        information_source_fingerprint=fp("new-source-same-family"),
        mechanism_fingerprint=fp("changed-mechanism"),
        decision_layer="changed-layer",
    )
    assert rr.preflight_proposal(tmp_path, proposal)["decision"] == "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE"


def test_operation_sha_tamper_and_count_mismatch_fail_before_apply(tmp_path: Path) -> None:
    tampered = reviewed_patch(
        rr.GENESIS,
        [{"op": "add_entity", "entity": entity("TAMPERED_OPERATION", information="tamper-source")}],
    )
    tampered["operations"][0]["entity"]["canonical_name"] = "Edited After Review"
    with pytest.raises(rr.RegistryError, match="PATCH_OPERATIONS_SHA256_MISMATCH"):
        rr.apply_patch(tmp_path / "sha", tampered)

    bad_count = reviewed_patch(
        rr.GENESIS,
        [{"op": "add_entity", "entity": entity("BAD_COUNT", information="count-source")}],
    )
    bad_count["operation_count"] = 2
    with pytest.raises(rr.RegistryError, match="PATCH_OPERATION_COUNT_MISMATCH"):
        rr.apply_patch(tmp_path / "count", bad_count)


@pytest.mark.parametrize(
    ("pin", "value"),
    [
        ("pinned_bootstrap_source_sha256", None),
        ("pinned_bootstrap_source_sha256", "not-a-sha"),
        ("pinned_outcome_blind_inventory_sha256", None),
        ("pinned_outcome_blind_inventory_sha256", "1234"),
    ],
)
def test_audited_bootstrap_requires_well_formed_pins(
    tmp_path: Path, pin: str, value: str | None
) -> None:
    patch = audited_patch(
        rr.GENESIS,
        [{"op": "add_entity", "entity": entity("PINNED", information="pinned-source")}],
    )
    if value is None:
        patch.pop(pin)
    else:
        patch[pin] = value
    with pytest.raises(rr.RegistryError, match="INVALID_SHA256"):
        rr.apply_patch(tmp_path, patch)


@pytest.mark.parametrize("status", ["CLOSED", "TOMBSTONED", "SUPERSEDED"])
@pytest.mark.parametrize("identity_kind", ["entity_id", "canonical_name", "alias"])
def test_exact_terminal_identity_reuse_blocks_without_parent_or_variant_marker(
    tmp_path: Path, status: str, identity_kind: str
) -> None:
    terminal = entity(
        "TERMINAL_IDENTITY",
        name="Terminal Canonical Name",
        information="terminal-identity-source",
        status=status,
        aliases=["Terminal Legacy Alias"],
        information_family="terminal-identity-family",
    )
    rr.apply_patch(
        tmp_path,
        audited_patch(rr.GENESIS, [{"op": "add_entity", "entity": terminal}]),
    )
    candidate = entity(
        "NEW_IDENTITY",
        name="Entirely New Name",
        specification="entirely-new-specification",
        information="entirely-new-information",
        mechanism="entirely-new-mechanism",
        layer="entirely-new-layer",
        information_family="entirely-new-family",
    )
    if identity_kind == "entity_id":
        candidate["entity_id"] = "TERMINAL_IDENTITY"
    elif identity_kind == "canonical_name":
        candidate["canonical_name"] = "Terminal Canonical Name"
    else:
        candidate["aliases"] = ["terminal_legacy_alias"]
    expected = "BLOCKED_SUPERSEDED_BRANCH" if status == "SUPERSEDED" else "BLOCKED_CLOSED_BRANCH"
    assert rr.preflight_proposal(tmp_path, {"candidate": candidate})["decision"] == expected


@pytest.mark.parametrize("location", ["proposal", "candidate"])
def test_plural_parent_entity_ids_enforce_terminal_ancestry(
    tmp_path: Path, location: str
) -> None:
    terminal = entity(
        "PLURAL_PARENT",
        information="plural-parent-old-source",
        mechanism="plural-parent-old-mechanism",
        layer="plural-parent-old-layer",
        status="CLOSED",
        information_family="plural-parent-old-family",
    )
    rr.apply_patch(
        tmp_path,
        audited_patch(rr.GENESIS, [{"op": "add_entity", "entity": terminal}]),
    )
    candidate = entity(
        "PLURAL_CHILD",
        information="plural-child-new-source",
        mechanism="plural-child-new-mechanism",
        layer="plural-child-new-layer",
        information_family="plural-child-new-family",
    )
    proposal: dict[str, object] = {"candidate": candidate}
    if location == "proposal":
        proposal["parent_entity_ids"] = ["PLURAL_PARENT"]
    else:
        candidate["parent_entity_ids"] = ["PLURAL_PARENT"]
    assert rr.preflight_proposal(tmp_path, proposal)["decision"] == "BLOCKED_CLOSED_BRANCH"


@pytest.mark.parametrize(
    ("status", "candidate_id", "candidate_name", "change_type", "expected"),
    [
        ("CLOSED", "FOO_R2", "Unrelated Display", "model", "BLOCKED_CLOSED_BRANCH"),
        ("TOMBSTONED", "UNRELATED_R3", "Foo Mechanism R3", "rename", "BLOCKED_CLOSED_BRANCH"),
        ("SUPERSEDED", "FOO_RETRY", "Foo Retry 4", "", "BLOCKED_SUPERSEDED_BRANCH"),
        ("CLOSED", "FOO_THRESHOLD", "Foo Threshold Repackaging", "threshold", "BLOCKED_CLOSED_BRANCH"),
        ("TOMBSTONED", "FOO_MODEL", "Foo Model", "model", "BLOCKED_CLOSED_BRANCH"),
        ("CLOSED", "PLAIN_NUMBER_RENAME", "Foo 2", "rename", "BLOCKED_CLOSED_BRANCH"),
        ("SUPERSEDED", "MARK_RENAME", "Foo Mk II", "rename", "BLOCKED_SUPERSEDED_BRANCH"),
        ("CLOSED", "NO_MARKER_2", "Foo Mechanism 2", "", "BLOCKED_CLOSED_BRANCH"),
        ("TOMBSTONED", "NO_MARKER_MK", "Foo Mechanism Mk II", "", "BLOCKED_CLOSED_BRANCH"),
        ("SUPERSEDED", "NO_MARKER_V2", "Foo Mechanism V2", "", "BLOCKED_SUPERSEDED_BRANCH"),
        ("CLOSED", "NO_MARKER_ATTEMPT", "Foo Mechanism Attempt2", "", "BLOCKED_CLOSED_BRANCH"),
        ("TOMBSTONED", "NO_MARKER_XGB", "Foo Mechanism XGBoost", "", "BLOCKED_CLOSED_BRANCH"),
    ],
)
def test_terminal_identity_stem_blocks_spoofed_family_and_fingerprints(
    tmp_path: Path,
    status: str,
    candidate_id: str,
    candidate_name: str,
    change_type: str,
    expected: str,
) -> None:
    terminal = entity(
        "FOO_MECHANISM",
        name="Foo Mechanism",
        aliases=["Foo Legacy"],
        information="foo-original-information",
        mechanism="foo-original-mechanism",
        layer="foo-original-layer",
        status=status,
        information_family="foo-original-family",
    )
    rr.apply_patch(
        tmp_path,
        audited_patch(rr.GENESIS, [{"op": "add_entity", "entity": terminal}]),
    )
    candidate = entity(
        candidate_id,
        name=candidate_name,
        specification=f"new-specification:{candidate_id}",
        information=f"spoofed-new-information:{candidate_id}",
        mechanism=f"spoofed-new-mechanism:{candidate_id}",
        layer=f"spoofed-new-layer:{candidate_id}",
        information_family=f"spoofed-new-family:{candidate_id}",
    )
    proposal: dict[str, object] = {"candidate": candidate}
    if change_type:
        proposal["change_type"] = change_type
    assert rr.preflight_proposal(tmp_path, proposal)["decision"] == expected


def test_lineage_stem_does_not_block_genuinely_distinct_named_source(tmp_path: Path) -> None:
    terminal = entity(
        "FOO_MECHANISM",
        name="Foo Mechanism",
        information="foo-source",
        status="CLOSED",
        information_family="foo-family",
    )
    rr.apply_patch(
        tmp_path,
        audited_patch(rr.GENESIS, [{"op": "add_entity", "entity": terminal}]),
    )
    distinct = entity(
        "BAR_R2",
        name="Bar Mechanism R2",
        information="bar-source",
        mechanism="bar-mechanism",
        layer="bar-layer",
        information_family="bar-family",
    )
    assert rr.preflight_proposal(tmp_path, {"candidate": distinct})["decision"] == "PASS_DISTINCT_INFORMATION_SOURCE"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("CLOSED", "BLOCKED_CLOSED_BRANCH"),
        ("TOMBSTONED", "BLOCKED_CLOSED_BRANCH"),
        ("SUPERSEDED", "BLOCKED_SUPERSEDED_BRANCH"),
    ],
)
def test_terminal_authoritative_artifact_overlap_blocks_family_rebranding(
    tmp_path: Path, status: str, expected: str
) -> None:
    terminal = entity(
        "ARTIFACT_HISTORY",
        name="Historical Alpha Source",
        information="historical-source",
        mechanism="historical-mechanism",
        layer="historical-layer",
        status=status,
        information_family="historical-family",
        authoritative_artifact_refs=["synthetic://frozen/branch-specific-source"],
    )
    rr.apply_patch(
        tmp_path,
        audited_patch(rr.GENESIS, [{"op": "add_entity", "entity": terminal}]),
    )
    candidate = entity(
        "TOTALLY_REBRANDED",
        name="Unrelated Surface Label",
        information="spoofed-new-source",
        mechanism="spoofed-new-mechanism",
        layer="spoofed-new-layer",
        information_family="spoofed-new-family",
        authoritative_artifact_refs=["SYNTHETIC://FROZEN/BRANCH-SPECIFIC-SOURCE"],
    )
    assert rr.preflight_proposal(tmp_path, {"candidate": candidate})["decision"] == expected


@pytest.mark.parametrize(
    "candidate_ref",
    [
        "D:/contracts/foo.json",
        "D:/contracts/./foo.json",
        "D:/contracts/sub/../foo.json",
        r"D:\contracts\sub\..\foo.json",
    ],
)
def test_authoritative_filesystem_reference_dot_segments_are_canonicalized(
    tmp_path: Path, candidate_ref: str
) -> None:
    terminal = entity(
        "FILESYSTEM_ARTIFACT_HISTORY",
        status="CLOSED",
        information_family="filesystem-artifact-old-family",
        authoritative_artifact_refs=["D:/contracts/foo.json"],
    )
    rr.apply_patch(
        tmp_path,
        audited_patch(rr.GENESIS, [{"op": "add_entity", "entity": terminal}]),
    )
    candidate = entity(
        "FILESYSTEM_ARTIFACT_REBRAND",
        information="filesystem-artifact-new-source",
        mechanism="filesystem-artifact-new-mechanism",
        layer="filesystem-artifact-new-layer",
        information_family="filesystem-artifact-new-family",
        authoritative_artifact_refs=[candidate_ref],
    )
    assert rr.preflight_proposal(tmp_path, {"candidate": candidate})["decision"] == "BLOCKED_CLOSED_BRANCH"


def test_active_authoritative_artifact_overlap_requires_review(tmp_path: Path) -> None:
    active = entity(
        "ACTIVE_ARTIFACT_HISTORY",
        information="active-old-source",
        information_family="active-old-family",
        authoritative_artifact_refs=["synthetic://frozen/active-branch-source"],
    )
    rr.apply_patch(tmp_path, reviewed_patch(rr.GENESIS, [{"op": "add_entity", "entity": active}]))
    candidate = entity(
        "ACTIVE_ARTIFACT_REBRAND",
        information="active-new-source",
        mechanism="active-new-mechanism",
        layer="active-new-layer",
        information_family="active-new-family",
        authoritative_artifact_refs=["synthetic://frozen/active-branch-source"],
    )
    assert rr.preflight_proposal(tmp_path, {"candidate": candidate})["decision"] == "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE"


def test_proposal_level_authoritative_artifact_overlap_blocks_terminal_history(tmp_path: Path) -> None:
    terminal = entity(
        "PROPOSAL_ARTIFACT_HISTORY",
        information="proposal-artifact-old-source",
        status="CLOSED",
        information_family="proposal-artifact-old-family",
        authoritative_artifact_refs=["synthetic://frozen/proposal-level-source"],
    )
    rr.apply_patch(
        tmp_path,
        audited_patch(rr.GENESIS, [{"op": "add_entity", "entity": terminal}]),
    )
    candidate = entity(
        "PROPOSAL_ARTIFACT_REBRAND",
        information="proposal-artifact-new-source",
        mechanism="proposal-artifact-new-mechanism",
        layer="proposal-artifact-new-layer",
        information_family="proposal-artifact-new-family",
    )
    candidate.pop("authoritative_artifact_refs")
    proposal = {
        "candidate": candidate,
        "authoritative_artifact_refs": ["synthetic://frozen/proposal-level-source"],
    }
    assert rr.preflight_proposal(tmp_path, proposal)["decision"] == "BLOCKED_CLOSED_BRANCH"


def test_distinct_source_without_authoritative_anchor_requires_review(tmp_path: Path) -> None:
    bootstrap(tmp_path)
    candidate = entity(
        "UNANCHORED_DISTINCT",
        information="unanchored-distinct-source",
        information_family="unanchored-distinct-family",
    )
    candidate.pop("authoritative_artifact_refs")
    decision = rr.preflight_proposal(tmp_path, {"candidate": candidate})
    assert decision["decision"] == "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE"
    assert any("authoritative distinct-source" in reason for reason in decision["reasons"])


@pytest.mark.parametrize("location", ["proposal", "candidate"])
@pytest.mark.parametrize(
    ("field", "reference"),
    [
        ("parent_entity_id", "Foo Legacy"),
        ("parent_entity_ids", ["Foo Legacy"]),
        ("base_entity_id", "CLOSED_FOO"),
        ("base_entity_ids", ["CLOSED_FOO"]),
        ("derived_from_entity_id", "CLOSED_FOO"),
        ("derived_from_entity_ids", ["CLOSED_FOO"]),
        ("equivalent_to", "CLOSED_FOO"),
        ("duplicate_with", "Foo Legacy"),
        ("canonical_or_duplicate_target", "CLOSED_FOO"),
        ("predecessor_entity_id", "Foo Legacy"),
        ("predecessor_entity_ids", ["Foo Legacy"]),
        ("replaces_entity_id", "CLOSED_FOO"),
    ],
)
def test_alias_resolved_terminal_lineage_fields_block(
    tmp_path: Path, location: str, field: str, reference: object
) -> None:
    terminal = entity(
        "CLOSED_FOO",
        name="Foo Mechanism",
        aliases=["Foo Legacy"],
        information="closed-foo-source",
        status="CLOSED",
        information_family="closed-foo-family",
    )
    rr.apply_patch(
        tmp_path,
        audited_patch(rr.GENESIS, [{"op": "add_entity", "entity": terminal}]),
    )
    candidate = entity(
        "UNRELATED_CHILD",
        name="Unrelated Child",
        information="unrelated-child-source",
        mechanism="unrelated-child-mechanism",
        layer="unrelated-child-layer",
        information_family="unrelated-child-family",
    )
    proposal: dict[str, object] = {"candidate": candidate}
    target = proposal if location == "proposal" else candidate
    target[field] = reference
    assert rr.preflight_proposal(tmp_path, proposal)["decision"] == "BLOCKED_CLOSED_BRANCH"


@pytest.mark.parametrize("field", ["equivalent_to", "duplicate_with", "canonical_or_duplicate_target"])
def test_active_equivalence_lineage_blocks_functional_redundancy(
    tmp_path: Path, field: str
) -> None:
    active = entity("ACTIVE_EQUIVALENT", aliases=["Active Equivalent Alias"])
    rr.apply_patch(tmp_path, reviewed_patch(rr.GENESIS, [{"op": "add_entity", "entity": active}]))
    candidate = entity(
        "DECLARED_EQUIVALENT",
        information="declared-new-source",
        mechanism="declared-new-mechanism",
        layer="declared-new-layer",
        information_family="declared-new-family",
        **{field: "Active Equivalent Alias"},
    )
    assert rr.preflight_proposal(tmp_path, {"candidate": candidate})["decision"] == "BLOCKED_FUNCTIONAL_REDUNDANCY"


def test_unknown_declared_lineage_reference_requires_review(tmp_path: Path) -> None:
    bootstrap(tmp_path)
    candidate = entity(
        "UNKNOWN_LINEAGE_CHILD",
        information="unknown-lineage-source",
        information_family="unknown-lineage-family",
        parent_entity_id="MISSING_PARENT",
    )
    assert rr.preflight_proposal(tmp_path, {"candidate": candidate})["decision"] == "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE"


@pytest.mark.parametrize("location", ["proposal_metadata", "candidate_metadata"])
def test_nested_metadata_terminal_lineage_resolves_alias(
    tmp_path: Path, location: str
) -> None:
    terminal = entity(
        "NESTED_LINEAGE_TERMINAL",
        aliases=["Nested Legacy Alias"],
        status="CLOSED",
        information_family="nested-lineage-family",
    )
    rr.apply_patch(
        tmp_path,
        audited_patch(rr.GENESIS, [{"op": "add_entity", "entity": terminal}]),
    )
    candidate = entity(
        "NESTED_LINEAGE_CHILD",
        information="nested-lineage-new-source",
        information_family="nested-lineage-new-family",
    )
    proposal: dict[str, object] = {"candidate": candidate}
    if location == "proposal_metadata":
        proposal["metadata"] = {"derived_from_entity_id": "Nested Legacy Alias"}
    else:
        candidate["metadata"] = {"derived_from_entity_id": "Nested Legacy Alias"}
    assert rr.preflight_proposal(tmp_path, proposal)["decision"] == "BLOCKED_CLOSED_BRANCH"


@pytest.mark.parametrize("location", ["proposal", "candidate"])
@pytest.mark.parametrize("identity_field", ["information_source", "feature_input_family"])
def test_raw_information_identity_overlap_cannot_be_hidden_by_new_fingerprint(
    tmp_path: Path, identity_field: str, location: str
) -> None:
    active = entity(
        "RAW_IDENTITY_ACTIVE",
        information="old-declared-fingerprint",
        mechanism="old-mechanism",
        layer="old-layer",
        information_family="old-family",
        **{identity_field: "same raw source"},
    )
    rr.apply_patch(tmp_path, reviewed_patch(rr.GENESIS, [{"op": "add_entity", "entity": active}]))
    candidate = entity(
        "RAW_IDENTITY_REBRAND",
        information="spoofed-new-fingerprint",
        mechanism="spoofed-new-mechanism",
        layer="spoofed-new-layer",
        information_family="spoofed-new-family",
    )
    proposal: dict[str, object] = {"candidate": candidate}
    target = proposal if location == "proposal" else candidate
    target[identity_field] = "Same-Raw_Source"
    assert rr.preflight_proposal(tmp_path, proposal)["decision"] == "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE"


def test_raw_information_identity_exact_surface_is_functional_redundancy(tmp_path: Path) -> None:
    active = entity(
        "RAW_SURFACE_ACTIVE",
        information="old-surface-fingerprint",
        mechanism="shared-raw-mechanism",
        layer="shared-raw-layer",
        information_family="old-surface-family",
        information_source="same raw source",
    )
    rr.apply_patch(tmp_path, reviewed_patch(rr.GENESIS, [{"op": "add_entity", "entity": active}]))
    candidate = entity(
        "RAW_SURFACE_REBRAND",
        information="new-surface-fingerprint",
        mechanism="shared-raw-mechanism",
        layer="shared-raw-layer",
        information_family="new-surface-family",
        information_source="Same Raw Source",
    )
    assert rr.preflight_proposal(tmp_path, {"candidate": candidate})["decision"] == "BLOCKED_FUNCTIONAL_REDUNDANCY"


def test_unresolved_raw_identity_placeholders_do_not_create_false_collision(tmp_path: Path) -> None:
    terminal = entity(
        "PLACEHOLDER_HISTORY",
        information="placeholder-old-fingerprint",
        status="CLOSED",
        information_family="placeholder-old-family",
        information_source="UNKNOWN",
        feature_input_family="UNAVAILABLE_OR_NOT_IMPORTED_TEMPORAL_FIREWALL",
    )
    rr.apply_patch(
        tmp_path,
        audited_patch(rr.GENESIS, [{"op": "add_entity", "entity": terminal}]),
    )
    candidate = entity(
        "GENUINELY_DISTINCT_PLACEHOLDER",
        information="placeholder-new-fingerprint",
        mechanism="placeholder-new-mechanism",
        layer="placeholder-new-layer",
        information_family="placeholder-new-family",
        information_source="UNKNOWN",
        feature_input_family="UNAVAILABLE_OR_NOT_IMPORTED_TEMPORAL_FIREWALL",
    )
    assert rr.preflight_proposal(tmp_path, {"candidate": candidate})["decision"] == "PASS_DISTINCT_INFORMATION_SOURCE"


@pytest.mark.parametrize("reader", ["current", "query", "resolve", "export", "preflight"])
def test_serving_reads_fail_closed_on_snapshot_manifest_hash_tamper(
    tmp_path: Path, reader: str
) -> None:
    _, applied = bootstrap(tmp_path)
    manifest_path = tmp_path / rr.SNAPSHOTS_DIR / applied["head_sha256"] / rr.MANIFEST_FILE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][rr.REGISTRY_FILE] = "0" * 64
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(rr.RegistryError, match="SNAPSHOT_INTEGRITY_INVALID"):
        if reader == "current":
            rr.current_state(tmp_path)
        elif reader == "query":
            rr.query_registry(tmp_path, entity_id="RAW_A2")
        elif reader == "resolve":
            rr.resolve_alias(tmp_path, "A2 Raw")
        elif reader == "export":
            rr.export_context(tmp_path, tmp_path / "tampered-context.json")
        else:
            rr.preflight_proposal(
                tmp_path,
                {"candidate": entity("AFTER_TAMPER", information="after-tamper-source")},
            )


@pytest.mark.parametrize("reader", ["query", "resolve", "export", "diff"])
def test_public_reads_fail_closed_on_event_chain_tamper(
    tmp_path: Path, reader: str
) -> None:
    _, first = bootstrap(tmp_path)
    second = rr.apply_patch(
        tmp_path,
        reviewed_patch(
            first["head_sha256"],
            [
                {
                    "op": "update_entity",
                    "entity": {
                        "entity_id": "RAW_A2",
                        "trial_ledger_failure_row_count": 3,
                    },
                }
            ],
        ),
    )
    events_path = tmp_path / rr.EVENTS_FILE
    event_rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    event_rows[0]["event_hash"] = "0" * 64
    events_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in event_rows),
        encoding="utf-8",
    )
    with pytest.raises(rr.RegistryError, match="EVENT_CHAIN_INVALID"):
        if reader == "query":
            rr.query_registry(tmp_path, entity_id="RAW_A2")
        elif reader == "resolve":
            rr.resolve_alias(tmp_path, "A2 Raw")
        elif reader == "export":
            rr.export_context(tmp_path, tmp_path / "event-tampered-context.json")
        else:
            rr.diff_snapshots(tmp_path, first["head_sha256"], second["head_sha256"])


def test_public_read_fails_closed_when_event_chain_is_missing(tmp_path: Path) -> None:
    bootstrap(tmp_path)
    (tmp_path / rr.EVENTS_FILE).unlink()
    with pytest.raises(rr.RegistryError, match="EVENT_CHAIN_HEAD_MISMATCH"):
        rr.query_registry(tmp_path, entity_id="RAW_A2")
