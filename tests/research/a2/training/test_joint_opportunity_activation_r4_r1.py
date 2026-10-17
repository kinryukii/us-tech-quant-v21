"""Synthetic compatibility checks; no real training, source or 2026 reads."""
import copy
import json
import pytest
from scripts.research.a2.training import joint_opportunity_activation_r4_r1 as wrapper


def spec():
    return dict(native=dict(inner=("H1","H2"), hidden_layer_sizes=(32,16), alpha=10),
                source=dict(path="synthetic/source",sha256="a"*64))


def test_json_list_tuple_roundtrip_is_exact_value_equivalent():
    actual=spec()
    stored=json.loads(json.dumps(actual))
    assert wrapper.canonical_specification(stored,actual)==stored


@pytest.mark.parametrize("change",["value","order","source","field","number_type"])
def test_canonical_view_rejects_any_scientific_or_source_change(change):
    stored=json.loads(json.dumps(spec()))
    changed=spec()
    if change=="value":changed["native"]["hidden_layer_sizes"]=(32,17)
    elif change=="order":changed["native"]["inner"]=("H2","H1")
    elif change=="source":changed["source"]["sha256"]="b"*64
    elif change=="number_type":changed["native"]["alpha"]=10.0
    else:changed["new_selection_freedom"]=True
    with pytest.raises(wrapper.execution.OpportunityBlocked,
                       match="ACTIVATION_CANONICAL_SPEC_VALUES_CHANGED"):
        wrapper.canonical_specification(stored,changed)


def test_compatibility_runs_original_worker_and_restores_process_local_view(monkeypatch):
    original=lambda run:spec()
    stored=json.loads(json.dumps(spec()))
    monkeypatch.setattr(wrapper.execution,"specification",original)
    monkeypatch.setattr(wrapper,"validate_binding",lambda *a:stored)
    def worker(run,**kwargs):
        assert wrapper.execution.specification(run)==stored
        assert kwargs["expected_matrix_sha"]==wrapper.ORIGINAL_MATRIX_SHA
        return dict(status="SYNTHETIC_DONE",new_fit_units=0)
    monkeypatch.setattr(wrapper.execution,"run_training",worker)
    result=wrapper.run_training_compatible("synthetic",expected_matrix_sha=wrapper.ORIGINAL_MATRIX_SHA,
                                           expected_binding_sha="c"*64)
    assert result["new_fit_units"]==0 and wrapper.execution.specification is original


def test_compatibility_restores_original_even_when_worker_fails(monkeypatch):
    original=lambda run:spec()
    monkeypatch.setattr(wrapper.execution,"specification",original)
    monkeypatch.setattr(wrapper,"validate_binding",lambda *a:json.loads(json.dumps(spec())))
    def worker(*a,**k):raise RuntimeError("synthetic_engineering_failure")
    monkeypatch.setattr(wrapper.execution,"run_training",worker)
    with pytest.raises(RuntimeError,match="synthetic_engineering_failure"):
        wrapper.run_training_compatible("synthetic",expected_matrix_sha=wrapper.ORIGINAL_MATRIX_SHA,
                                       expected_binding_sha="c"*64)
    assert wrapper.execution.specification is original
