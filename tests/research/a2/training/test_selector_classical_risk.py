"""C11 controller guard tests; synthetic files only, no real inputs or fitting."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts.research.a2.training import selector_classical_risk as sut
from scripts.research.a2.evaluation import selector_account_compare as reader


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def write_formal_freeze(root, d):
    write_json(root / "DESIGN_FREEZE.json", d)
    review = dict(status="PASS", research_id=sut.ev.RESEARCH_ID,
                  design_sha256=sut.sha(root / "DESIGN_FREEZE.json"),
                  source_pins=d["sources"],
                  pre_execution_counters=dict(fits=0, risk_state_attempts=0, outcome_reads=0))
    write_json(root / "FORMAL_FREEZE_REVIEW.json", review)
    write_json(root / "DESIGN_FREEZE_SHA.json",
               dict(sha256=sut.sha(root / "DESIGN_FREEZE.json"),
                    formal_review_sha256=sut.sha(root / "FORMAL_FREEZE_REVIEW.json")))


def fixture_root(tmp_path, monkeypatch):
    root = tmp_path / "synthetic_consumer"
    root.mkdir()
    monkeypatch.setattr(sut, "safe_d", lambda path: Path(path))
    monkeypatch.setattr(sut, "assert_safe_output_path", lambda *a, **k: None)
    monkeypatch.setattr(sut.ev, "validate_design", lambda design: design.get("evaluation", {}))
    source = root / "synthetic_owner.py"
    source.write_text("# Synthetic source pin only\n", encoding="utf-8")
    d = dict(synthetic_validation_only=True, research_id=sut.ev.RESEARCH_ID,
             sources={str(source): sut.sha(source)}, risk_eligible_families=[],
             blocked_roles={cid: "BLOCKED_SOURCE" for cid in sut.ev.B_ROLES})
    for key in ("features", "raw_score", "risk_review", "completion_dag", "input_qualification"):
        p = root / (key + ".json")
        value = {"active_physical_estimators": []} if key == "completion_dag" else {"synthetic": True}
        write_json(p, value)
        d[key] = dict(path=str(p), sha256=sut.sha(p))
    write_json(root / "run_config.json", dict(research_id=sut.ev.RESEARCH_ID,
        strategy_id="V24", research_line="C_SELECTOR", results_directory=str(root / "results")))
    write_formal_freeze(root, d)
    return root, d, source


def test_controller_and_rule_roles_agree_and_risk_roles_remain_blocked():
    assert sut.ev.A_ROLES == sut.rules.BASE_ROLES
    assert sut.ev.B_ROLES == sut.rules.RISK_ROLES
    assert sut.ev.SANITY_ROLES == sut.rules.SANITY_ROLES
    assert len(sut.ev.ROLES) == 20
    assert len(sut.ev.A_ROLES) == 8 and len(sut.ev.B_ROLES) == 10


def test_source_pin_drift_rejected_before_real_input(tmp_path, monkeypatch):
    root, _, source = fixture_root(tmp_path, monkeypatch)
    source.write_text("# Altered synthetic source\n", encoding="utf-8")
    with pytest.raises(ValueError, match="PIN_CHANGED"):
        sut.checked(root)


def test_freeze_byte_drift_rejected_before_source_read(tmp_path, monkeypatch):
    root, d, _ = fixture_root(tmp_path, monkeypatch)
    d["changed_after_freeze"] = True
    write_json(root / "DESIGN_FREEZE.json", d)
    monkeypatch.setattr(sut, "pin", lambda item: pytest.fail("Pin/body touched after freeze drift"))
    with pytest.raises(ValueError, match="FREEZE_CHANGED"):
        sut.checked(root)


def test_active_risk_fit_in_dag_rejected(tmp_path, monkeypatch):
    root, d, _ = fixture_root(tmp_path, monkeypatch)
    p = Path(d["completion_dag"]["path"])
    write_json(p, dict(active_physical_estimators=["UNAUTHORIZED_SYNTHETIC_FIT"]))
    d["completion_dag"]["sha256"] = sut.sha(p)
    write_formal_freeze(root, d)
    with pytest.raises(ValueError, match="NO_FIT"):
        sut.checked(root)


@pytest.mark.parametrize("mode", ["future_only", "future_second_rowgroup", "null_clock", "missing_clock"])
def test_parquet_footer_rejects_future_or_unknown_before_body(tmp_path, monkeypatch, mode):
    p = tmp_path / (mode + ".parquet")
    if mode == "missing_clock":
        table = pa.table({"synthetic_feature": [1., 2.]})
    else:
        clocks = (["2026-01-02", "2026-01-05"] if mode == "future_only" else
                  ["2025-12-30", "2026-01-02"] if mode == "future_second_rowgroup" else
                  ["2024-01-03", None])
        table = pa.Table.from_pandas(pd.DataFrame(dict(signal_date=pd.to_datetime(clocks), synthetic_feature=[1., 2.])), preserve_index=False)
    pq.write_table(table, p, row_group_size=1)
    monkeypatch.setattr(reader.pq, "read_table", lambda *a, **k: pytest.fail("Rejected footer reached data body"))
    with pytest.raises(ValueError, match="BOUNDARY"):
        sut.pre2026(p, ["synthetic_feature"], "signal_date")


def test_input_frame_future_raw_footer_fails_before_features(tmp_path, monkeypatch):
    p = tmp_path / "future_synthetic_raw.parquet"
    pq.write_table(pa.Table.from_pandas(pd.DataFrame(dict(signal_date=pd.to_datetime(["2026-01-02"]))), preserve_index=False), p)
    calls = []
    def pin(item):
        calls.append(item["path"])
        assert len(calls) == 1, "Feature access must not follow rejected raw footer"
        return p
    monkeypatch.setattr(sut, "pin", pin)
    monkeypatch.setattr(reader.pq, "read_table", lambda *a, **k: pytest.fail("Future body read"))
    with pytest.raises(ValueError, match="BOUNDARY"):
        sut.input_frame(dict(raw_score={"path": str(p)}, features={"path": "SYNTHETIC_NEVER_OPEN"}))
    assert len(calls) == 1


def test_repeated_assembly_stops_before_input_frame(tmp_path, monkeypatch):
    root = tmp_path / "assembly"
    root.mkdir()
    write_json(root / "SCORE_ASSEMBLY.json", dict(synthetic_only=True))
    monkeypatch.setattr(sut, "checked", lambda path: ({}, {}))
    monkeypatch.setattr(sut, "input_frame", lambda *a: pytest.fail("Repeated assembly reached inputs"))
    with pytest.raises(FileExistsError, match="NO_DUPLICATE_ASSEMBLY"):
        sut.assemble(root)


def test_repeated_evaluation_stops_before_legacy_outcome_read(tmp_path, monkeypatch):
    root = tmp_path / "evaluation"
    out = root / "diagnostics" / "selector_evidence"
    out.mkdir(parents=True)
    write_json(out / "SELECTION_EVIDENCE.json", dict(synthetic_only=True))
    monkeypatch.setattr(sut, "checked", lambda path: ({"results_directory": str(root / "results")}, {}))
    monkeypatch.setattr(sut, "assert_safe_output_path", lambda *a, **k: None)
    monkeypatch.setattr(sut.ev, "validate_legacy", lambda *a: pytest.fail("Repeated evaluation reached legacy"))
    with pytest.raises(FileExistsError, match="NO_DUPLICATE_EVALUATION"):
        sut.evaluate(root)


def test_valid_pinned_formal_review_allows_metadata_check_only(tmp_path, monkeypatch):
    root, d, _ = fixture_root(tmp_path, monkeypatch)
    _, checked = sut.checked(root)
    assert checked == d


@pytest.mark.parametrize("field,value", [
    ("status", "FAILED"),
    ("research_id", "OTHER_SYNTHETIC_RESEARCH"),
    ("design_sha256", "0" * 64),
    ("source_pins", {}),
    ("pre_execution_counters", dict(fits=1, risk_state_attempts=0, outcome_reads=0)),
    ("pre_execution_counters", dict(fits=0, risk_state_attempts=1, outcome_reads=0)),
    ("pre_execution_counters", dict(fits=0, risk_state_attempts=0, outcome_reads=1)),
])
def test_review_semantic_tamper_rejected_even_with_updated_checksum(tmp_path, monkeypatch, field, value):
    root, _, _ = fixture_root(tmp_path, monkeypatch)
    path = root / "FORMAL_FREEZE_REVIEW.json"
    review = json.loads(path.read_text(encoding="utf-8"))
    review[field] = value
    write_json(path, review)
    manifest_path = root / "DESIGN_FREEZE_SHA.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["formal_review_sha256"] = sut.sha(path)
    write_json(manifest_path, manifest)
    with pytest.raises(ValueError, match="FORMAL_REVIEW_REQUIRED"):
        sut.checked(root)


def test_review_byte_tamper_rejected_without_updated_checksum(tmp_path, monkeypatch):
    root, _, _ = fixture_root(tmp_path, monkeypatch)
    path = root / "FORMAL_FREEZE_REVIEW.json"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="FORMAL_REVIEW_REQUIRED"):
        sut.checked(root)


def test_partial_score_panel_preserved_and_assembly_stops_before_inputs(tmp_path, monkeypatch):
    root = tmp_path / "partial_assembly"
    panel = root / f"predictions/scores_{sut.ev.A_ROLES[0]}_pre2026.parquet"
    panel.parent.mkdir(parents=True)
    panel.write_bytes(b"synthetic unfinished panel bytes")
    monkeypatch.setattr(sut, "checked", lambda path: ({}, {}))
    monkeypatch.setattr(sut, "input_frame", lambda *a: pytest.fail("Partial assembly reached inputs"))
    with pytest.raises(FileExistsError, match="NO_DUPLICATE_ASSEMBLY"):
        sut.assemble(root)
    assert panel.read_bytes() == b"synthetic unfinished panel bytes"
    assert not (root / "SCORE_ASSEMBLY.json").exists()


def test_partial_diagnosis_preserved_and_evaluation_stops_before_legacy_read(tmp_path, monkeypatch):
    root = tmp_path / "partial_evaluation"
    panel = root / "diagnostics/selector_evidence/PRIMARY_DAILY_EDGE.parquet"
    panel.parent.mkdir(parents=True)
    panel.write_bytes(b"synthetic unfinished diagnostic bytes")
    monkeypatch.setattr(sut, "checked", lambda path: ({"results_directory": str(root / "results")}, {}))
    monkeypatch.setattr(sut, "assert_safe_output_path", lambda *a, **k: None)
    monkeypatch.setattr(sut.ev, "validate_legacy", lambda *a: pytest.fail("Partial evaluation reached legacy"))
    with pytest.raises(FileExistsError, match="NO_DUPLICATE_EVALUATION"):
        sut.evaluate(root)
    assert panel.read_bytes() == b"synthetic unfinished diagnostic bytes"
    assert not (panel.parent / "SELECTION_EVIDENCE.json").exists()


def test_partial_delivery_preserved_and_report_stops_before_evidence_read(tmp_path, monkeypatch):
    root = tmp_path / "partial_report"
    output = root / "results/FINAL_REPORT.md"
    output.parent.mkdir(parents=True)
    output.write_text("synthetic unfinished report", encoding="utf-8")
    monkeypatch.setattr(sut, "checked", lambda path: ({"results_directory": str(output.parent)}, {}))
    monkeypatch.setattr(sut, "assert_safe_output_path", lambda *a, **k: None)
    monkeypatch.setattr(sut, "readj", lambda *a: pytest.fail("Partial report reached evidence"))
    with pytest.raises(FileExistsError, match="NO_DUPLICATE_REPORT"):
        sut.report(root)
    assert output.read_text(encoding="utf-8") == "synthetic unfinished report"


@pytest.mark.parametrize("mode", ["future_year", "missing_year", "null_year", "no_statistics", "float_year", "string_year"])
def test_report_rejects_unknown_or_future_year_footer_before_body(tmp_path, monkeypatch, mode):
    root = tmp_path / ("synthetic_report_" + mode)
    results = root / "results"
    results.mkdir(parents=True)
    write_json(root / "DESIGN_FREEZE.json", dict(synthetic_only=True))
    freeze_sha = sut.sha(root / "DESIGN_FREEZE.json")
    mp = root / "diagnostics/selector_evidence/MECHANISM_YEAR.parquet"
    mp.parent.mkdir(parents=True)
    if mode == "missing_year": table = pa.table({"synthetic_coordinate": [1.]})
    elif mode == "null_year": table = pa.table({"year": pa.array([None], type=pa.int64())})
    elif mode == "float_year": table = pa.table({"year": [2024.5]})
    elif mode == "string_year": table = pa.table({"year": ["2024"]})
    else: table = pa.table({"year": [2026 if mode == "future_year" else 2024]})
    pq.write_table(table, mp, write_statistics=mode != "no_statistics")
    evidence = dict(design_freeze_sha256=freeze_sha, test2026_locked=True,
        strict_PIT_promotion_eligible=False, status="SYNTHETIC_ONLY", research_supported_roles=[],
        tests=[], numeric_count=147, exposure_count=169, bootstrap={"critical_max_t": 1.},
        diagnostics={mp.name: dict(path=str(mp), sha256=sut.sha(mp))})
    write_json(results / "SELECTION_EVIDENCE.json", evidence)
    write_json(root / "RISK_FIT_LEDGER.json", dict(physical_fits=0, design_freeze_sha256=freeze_sha))
    monkeypatch.setattr(sut, "checked", lambda path: ({"results_directory": str(results)}, {}))
    monkeypatch.setattr(sut, "assert_safe_output_path", lambda *a, **k: None)
    monkeypatch.setattr(sut.pd, "read_parquet", lambda *a, **k: pytest.fail("Rejected report footer reached body"))
    with pytest.raises(ValueError, match="MECHANISM_SUMMARY_(?:INTEGER_)?YEAR"):
        sut.report(root)


@pytest.mark.parametrize("path", ["C:/synthetic", "E:/synthetic", "F:/synthetic", "D:relative", "relative"])
def test_non_d_or_relative_path_rejected_without_stat(path, monkeypatch):
    monkeypatch.setattr(sut.os, "lstat", lambda *a: pytest.fail("Rejected path probed filesystem"))
    with pytest.raises(ValueError, match="ONLY_D_PATH_ALLOWED"):
        sut.safe_d(path)
