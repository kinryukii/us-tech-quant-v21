"""Economic identities are distinct even when file hashes are internally valid.

All mutations target task-owned synthetic fixtures; no real source is rewritten.
"""
import csv
from dataclasses import replace
import hashlib
import json

import pytest

from apps.demo_console.adapters.artifact_reader import ArtifactError
from apps.demo_console.adapters.decision_reader import load_overview
from apps.demo_console.adapters.system_status_reader import read_freeze
from apps.demo_console.config.demo_config import BASELINE_ID


def _repin_manifest(config, mutate):
    assert config.manifest_path.parent.name.startswith("test-")
    manifest = json.loads(config.manifest_path.read_text(encoding="utf-8"))
    mutate(manifest)
    data = json.dumps(manifest).encode("utf-8")
    config.manifest_path.write_bytes(data)
    return replace(config, manifest_sha256=hashlib.sha256(data).hexdigest())


def _repin_hash_rows(config, mutate):
    assert config.hash_manifest_path.parent.name.startswith("test-")
    with config.hash_manifest_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields, rows = reader.fieldnames, list(reader)
    mutate(rows)
    with config.hash_manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    sha = hashlib.sha256(config.hash_manifest_path.read_bytes()).hexdigest()
    config = replace(config, hash_manifest_sha256=sha)
    return _repin_manifest(config, lambda m: m["artifact_hash_manifest"].update(sha256=sha))


def test_raw_control_has_precise_human_label_and_baseline_identity(make_overview_config):
    model = load_overview(config=make_overview_config())
    assert model.error is None
    assert model.provenance.strategy_identity == "Raw A2 control · historical portfolio"
    assert model.provenance.replay_identity == BASELINE_ID
    assert model.rx_accepted_changes is None and model.rx_prevented_changes is None


@pytest.mark.parametrize("field,value", [
    ("schema", "COMPARISON_SNAPSHOT"),
    ("source_experiment", "OTHER_RESEARCH"),
    ("frozen_baseline_name", "RAW_A2_PLUS_RX"),
])
def test_other_research_identity_rejected_despite_valid_sha(make_overview_config, field, value):
    config = _repin_manifest(make_overview_config(), lambda m: m.update({field: value}))
    with pytest.raises(ArtifactError, match="FREEZE_IDENTITY_MISMATCH"):
        read_freeze(config)


@pytest.mark.parametrize("field,value", [
    ("model_family", "OtherModel"),
    ("config_fingerprint", "0" * 64),
    ("source_fingerprint", "0" * 64),
    ("supplemental_full_pre2026_model", {"used_for_frozen_oof_predictions": True}),
])
def test_changed_alpha_or_full_sample_model_cannot_claim_oof_identity(make_overview_config, field, value):
    config = _repin_manifest(make_overview_config(), lambda m: m["contracts"]["A2"].update({field: value}))
    with pytest.raises(ArtifactError, match="FREEZE_IDENTITY_MISMATCH"):
        read_freeze(config)


@pytest.mark.parametrize("field,value", [
    ("artifact_id", "a_top20"),
    ("category", "COMPARISON"),
    ("role", "A_top20_selections"),
    ("immutable", "False"),
])
def test_non_a2_result_role_rejected_even_with_matching_path_and_hash(make_overview_config, field, value):
    config = _repin_hash_rows(make_overview_config(), lambda rows: rows[0].update({field: value}))
    with pytest.raises(ArtifactError, match="FREEZE_ARTIFACT_ROLE_MISMATCH"):
        read_freeze(config)


def test_ambiguous_artifact_role_rejected(make_overview_config):
    config = _repin_hash_rows(make_overview_config(), lambda rows: rows.append(dict(rows[0])))
    with pytest.raises(ArtifactError, match="FREEZE_ARTIFACT_ROLE_MISMATCH"):
        read_freeze(config)


def test_other_producer_cannot_inherit_original_baseline_binding(make_overview_config):
    config = _repin_hash_rows(make_overview_config(), lambda rows: rows[-1].update(sha256="0" * 64))
    with pytest.raises(ArtifactError, match="FREEZE_PRODUCER_BINDING_MISMATCH"):
        read_freeze(config)
