"""Synthetic chart overlays cannot change the explicit frozen execution reader."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from apps.demo_console.adapters import selected_strategies_reader as reader
from apps.demo_console.tests.test_selected_strategies import history_package
from scripts.common import storage_paths
from scripts.research.a2.evaluation import selected_performance_update

@pytest.fixture
def overlay(tmp_path, monkeypatch):
    base = tmp_path / "latest.json"
    payload = history_package("HGB_TOP20_RISK_R1")
    base.write_text(json.dumps(payload), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"policy_id": payload["policy_id"]}), encoding="utf-8")
    reference = {"schema": "HGB_DISPLAY_PERFORMANCE_REFERENCE_V1", "policy_id": payload["policy_id"],
        "base_package_sha256": sha256(base.read_bytes()).hexdigest(),
        "performance_manifest": {"path": str(manifest), "sha256": sha256(manifest.read_bytes()).hexdigest()}}
    sidecar = tmp_path / "performance_reference.json"
    sidecar.write_text(json.dumps(reference), encoding="utf-8")
    monkeypatch.setattr(reader, "package_path", lambda: base)
    monkeypatch.setattr(storage_paths, "resolve", lambda: SimpleNamespace(backtest_root=tmp_path))
    calls = []
    def merge(package, content, path, *, history_root=None):
        assert Path(history_root) == base.parent / "history"
        calls.append(path)
        return deepcopy(package)
    monkeypatch.setattr(selected_performance_update, "merge_extension", merge)
    reader._display_merge.cache_clear()
    yield base, manifest, sidecar, reference, calls
    reader._display_merge.cache_clear()

def test_default_chart_reader_retains_exact_execution_identity_and_bounds_cache(overlay):
    base, manifest, sidecar, ref, calls = overlay
    explicit = reader.load_package(base)
    assert calls == [] and "display_binding_sha256" not in explicit
    display = reader.load_package()
    assert display["package_sha256"] == explicit["package_sha256"]
    assert display["strategies"] == explicit["strategies"]
    assert reader.package_observation_sha256(base) == ref["base_package_sha256"]
    assert reader.package_observation_sha256() == display["display_binding_sha256"]
    display["strategies"]["HGB_DIAG_5"]["application"]["rows"].clear()
    assert reader.load_package()["strategies"] == explicit["strategies"]
    assert len(calls) == 1
    assert reader._display_merge.cache_info().maxsize == reader._display_merge.cache_info().currsize == 1

def test_next_execution_package_does_not_inherit_stale_overlay(overlay):
    base, manifest, sidecar, ref, calls = overlay
    content = json.loads(base.read_bytes()); content["generated_at"] = "2026-02-04T01:00:00+00:00"
    base.write_text(json.dumps(content), encoding="utf-8")
    assert "display_binding_sha256" not in reader.load_package()
    assert reader.package_observation_sha256() == sha256(base.read_bytes()).hexdigest()
    assert calls == []

def test_mutated_manifest_is_observed_but_rejected_before_merge(overlay):
    base, manifest, sidecar, ref, calls = overlay
    before = reader.package_observation_sha256()
    manifest.write_text('{"policy_id":"altered"}', encoding="utf-8")
    assert reader.package_observation_sha256() != before
    with pytest.raises(ValueError, match="display_manifest_hash_changed"):
        reader.load_package()
    assert calls == []
    assert reader.load_package(base)["package_sha256"] == ref["base_package_sha256"]

def test_overlay_cannot_change_current_scores_or_targets(overlay, monkeypatch):
    base, manifest, sidecar, ref, calls = overlay
    def bad_merge(package, *args, **kwargs):
        result = deepcopy(package); result["strategies"]["HGB_DIAG_5"]["application"]["target_cash_weight"] = .1
        return result
    original = deepcopy(reader.load_package(base)["strategies"]["HGB_DIAG_5"]["application"])
    monkeypatch.setattr(selected_performance_update, "merge_extension", bad_merge)
    with pytest.raises(ValueError, match="display_execution_targets_changed"):
        reader.load_package()
    assert reader.load_package(base)["strategies"]["HGB_DIAG_5"]["application"] == original

def test_reference_cannot_point_outside_backtest_root(overlay, monkeypatch):
    base, manifest, sidecar, ref, calls = overlay
    monkeypatch.setattr(storage_paths, "resolve", lambda: SimpleNamespace(backtest_root=base.parent / "other"))
    with pytest.raises(ValueError, match="display_manifest_outside_backtest"):
        reader.load_package()
    assert reader.load_package(base)["package_sha256"] == ref["base_package_sha256"]


def test_overlay_cannot_change_current_model_scores(overlay, monkeypatch):
    base, manifest, sidecar, ref, calls = overlay
    def bad_merge(package, *args, **kwargs):
        result = deepcopy(package); result["shared_scores"]["current"]["reason"] = "changed score source"
        return result
    monkeypatch.setattr(selected_performance_update, "merge_extension", bad_merge)
    with pytest.raises(ValueError, match="display_current_scores_changed"):
        reader.load_package()
    assert reader.load_package(base)["package_sha256"] == ref["base_package_sha256"]


def test_warm_overlay_returns_complete_isolated_package_with_one_tree_copy(overlay, monkeypatch):
    base, manifest, sidecar, ref, calls = overlay
    explicit = reader.load_package(base)
    expected = deepcopy(explicit)
    expected["display_binding_sha256"] = reader.package_observation_sha256()
    expected["display_performance_reference"] = deepcopy(ref)
    # Warm the immutable merge, then count only complete package-tree copies.
    assert reader.load_package() == expected
    real_copy = reader.deepcopy
    full_copies = []
    def copy(value):
        if isinstance(value, dict) and "strategies" in value:
            full_copies.append(value)
        return real_copy(value)
    monkeypatch.setattr(reader, "deepcopy", copy)
    result = reader.load_package()
    assert result == expected and len(full_copies) == 1
    result["strategies"]["HGB_DIAG_5"]["application"]["rows"].clear()
    assert reader.load_package() == expected
    assert reader.load_package(base) == explicit
    assert len(calls) == 1

def test_ml_base_reader_does_not_open_or_merge_performance_overlay(overlay,monkeypatch):
    base,manifest,sidecar,ref,calls=overlay
    expected=reader.load_package(base)
    def forbidden(*args,**kwargs):
        raise AssertionError("ML base read must not inspect a performance overlay")
    forbidden.cache_clear=reader._display_merge.cache_clear
    monkeypatch.setattr(reader,"_display_reference",forbidden)
    monkeypatch.setattr(reader,"_display_merge",forbidden)
    monkeypatch.setattr(selected_performance_update,"merge_extension",forbidden)
    real_open=Path.open
    observed=[]
    def bounded_open(path,*args,**kwargs):
        assert path.resolve() not in {manifest.resolve(),sidecar.resolve()}
        observed.append(path.resolve())
        return real_open(path,*args,**kwargs)
    monkeypatch.setattr(Path,"open",bounded_open)
    result=reader.load_package(include_performance=False)
    assert result==expected and calls==[]
    assert reader.package_observation_sha256(include_performance=False)==ref["base_package_sha256"]
    assert set(observed)=={base.resolve()}
    result["strategies"]["HGB_DIAG_5"]["application"]["rows"].clear()
    assert reader.load_package(include_performance=False)==expected


def test_ml_base_reader_retains_original_validation_and_rejects_invalid_option(overlay):
    base,*_=overlay
    with pytest.raises(ValueError,match="include_performance"):
        reader.load_package(include_performance=0)
    with pytest.raises(ValueError,match="include_performance"):
        reader.package_observation_sha256(include_performance=0)
    base.write_text('{"invalid":"synthetic"}',encoding="utf-8")
    with pytest.raises(ValueError):
        reader.load_package(include_performance=False)


def test_native_ml_calendar_matches_full_base_without_tree_copy_or_overlay(overlay, monkeypatch):
    base, manifest, sidecar, reference, calls = overlay
    expected = reader.load_package(base)
    dates = reader.workspace_dates(expected)
    def forbidden(*args, **kwargs):
        pytest.fail("Native calendar must not copy the package tree or read an overlay")
    monkeypatch.setattr(reader, "deepcopy", forbidden)
    monkeypatch.setattr(reader, "_display_reference", forbidden)
    real_open = Path.open
    opened = []
    def base_only(path, *args, **kwargs):
        assert path.resolve() == base.resolve()
        opened.append(path.resolve())
        return real_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", base_only)
    result = reader.load_workspace_calendar()
    assert result == {"available_dates": dates, "package_sha256": expected["package_sha256"],
        "package_path": expected["package_path"], "policy_id": expected["policy_id"]}
    assert isinstance(result["available_dates"], tuple) and opened == [base.resolve()]
    assert calls == []
    result["available_dates"] = ()
    assert reader.load_workspace_calendar()["available_dates"] == dates


def test_native_ml_calendar_warm_content_change_keeps_original_validation(overlay):
    import os
    base, *_ = overlay
    before = reader.load_workspace_calendar(base)
    raw = base.read_bytes()
    stat = base.stat()
    payload = json.loads(raw)
    for strategy in payload["strategies"].values():
        strategy["application"]["signal_date"] = "2026-02-04"
    changed = json.dumps(payload).encode("utf-8")
    assert len(changed) == len(raw)
    base.write_bytes(changed)
    os.utime(base, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    current = reader.load_workspace_calendar(base)
    full = reader.load_package(base, include_performance=False)
    assert current["available_dates"] == reader.workspace_dates(full)
    assert current["available_dates"] != before["available_dates"]
    assert current["package_sha256"] == full["package_sha256"] != before["package_sha256"]
    payload["strategies"][reader.STRATEGY_IDS[0]]["summary"]["end_nav"] = 123.
    base.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError) as projected:
        reader.load_workspace_calendar(base)
    with pytest.raises(ValueError) as complete:
        reader.load_package(base, include_performance=False)
    assert str(projected.value) == str(complete.value)
    assert reader._decode.cache_info().maxsize == reader._decode.cache_info().currsize == 1


def test_native_ml_calendar_retains_bounded_read_and_invalid_json_rejection(overlay, monkeypatch):
    base, *_ = overlay
    reader.load_workspace_calendar(base)
    with monkeypatch.context() as bounded:
        bounded.setattr(reader, "_MAX_BYTES", 4)
        with pytest.raises(ValueError, match="package_size"):
            reader.load_workspace_calendar(base)
    for raw in (b'{"schema_version":1,"schema_version":1}', b'{"score":NaN}'):
        base.write_bytes(raw)
        with pytest.raises(ValueError) as projected:
            reader.load_workspace_calendar(base)
        with pytest.raises(ValueError) as complete:
            reader.load_package(base, include_performance=False)
        assert str(projected.value) == str(complete.value)


def test_clear_cache_drops_warm_display_package_and_requalifies_same_bytes(overlay):
    base, manifest, sidecar, reference, calls = overlay
    files = {path: path.read_bytes() for path in (base, manifest, sidecar)}
    first = reader.load_package()
    assert reader.load_package() == first and len(calls) == 1
    assert reader._decode.cache_info().currsize == reader._display_merge.cache_info().currsize == 1
    reader.clear_cache()
    assert reader._decode.cache_info().currsize == reader._display_merge.cache_info().currsize == 0
    assert reader.load_package() == first and len(calls) == 2
    assert reader._decode.cache_info().currsize == reader._display_merge.cache_info().currsize == 1
    assert {path: path.read_bytes() for path in files} == files


def test_clear_cache_rechecks_original_target_guard_instead_of_reusing_old_merge(overlay, monkeypatch):
    base, manifest, sidecar, reference, calls = overlay
    files = {path: path.read_bytes() for path in (base, manifest, sidecar)}
    first = reader.load_package()
    assert reader.load_package() == first and len(calls) == 1
    def changed_target(package, *args, **kwargs):
        result = deepcopy(package)
        result["strategies"]["HGB_DIAG_5"]["application"]["target_cash_weight"] = .1
        return result
    monkeypatch.setattr(selected_performance_update, "merge_extension", changed_target)
    reader.clear_cache()
    with pytest.raises(ValueError, match="display_execution_targets_changed"):
        reader.load_package()
    assert reader._display_merge.cache_info().currsize == 0
    assert {path: path.read_bytes() for path in files} == files
