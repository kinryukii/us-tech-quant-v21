from __future__ import annotations

import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pandas as pd
import pytest


SCRIPT_DIR = Path(__file__).parents[1] / "scripts" / "storage"
sys.path.insert(0, str(SCRIPT_DIR))
spec = importlib.util.spec_from_file_location("refresh_13f_quarter_test", SCRIPT_DIR / "refresh_13f_quarter.py")
quarter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quarter)


def managers():
    return pd.DataFrame([{"manager_id": "pershing_square", "manager_name": "Pershing", "cik": "1336528",
                          "enabled": "True", "active_from_quarter": "2020Q1", "active_to_quarter": "",
                          "top_n": "100", "protected_top_n": "20", "manager_weight": "1", "required_for_gate": "True"}])


def test_manager_activation_and_fixed_selection_contract():
    registry = managers()
    assert len(quarter.active_managers(registry, "2026Q2")) == 1
    registry.loc[0, "active_to_quarter"] = "2026Q1"
    with pytest.raises(ValueError, match="No applicable managers"):
        quarter.active_managers(registry, "2026Q2")
    registry.loc[0, "active_to_quarter"] = ""
    registry.loc[0, "top_n"] = "50"
    with pytest.raises(ValueError, match="Top100"):
        quarter.active_managers(registry, "2026Q2")


def applicable_registry():
    incumbent = managers().iloc[0].to_dict()
    sa = {**incumbent, "manager_id": "sa", "manager_name": "SA", "cik": "1234567",
          "active_from_quarter": "2024Q3", "required_for_gate": "False", "manager_weight": "2"}
    future = {**incumbent, "manager_id": "future", "cik": "7654321", "active_from_quarter": "2027Q1"}
    disabled = {**incumbent, "manager_id": "disabled", "cik": "7654322", "enabled": "False"}
    return pd.DataFrame([incumbent, sa, future, disabled])


def test_manager_roster_uses_registered_start_and_has_no_automatic_expiry():
    registry = applicable_registry()
    assert quarter.active_managers(registry, "2024Q2").manager_id.tolist() == ["pershing_square"]
    first = quarter.active_managers(registry, "2024Q3")
    assert first.manager_id.tolist() == ["pershing_square", "sa"]
    assert first.required_for_gate.tolist() == [True, False]
    assert first.manager_weight.tolist() == [1, 2]
    # Open-ended registry applicability remains valid well beyond two quarters.
    assert quarter.active_managers(registry, "2026Q2").manager_id.tolist() == ["pershing_square", "sa"]
    registry.loc[1, "active_to_quarter"] = "2025Q1"
    assert "sa" in quarter.active_managers(registry, "2025Q1").manager_id.tolist()
    assert "sa" not in quarter.active_managers(registry, "2025Q2").manager_id.tolist()


@pytest.mark.parametrize("value", ["", "2026Q0", "2026Q5", "2026q1", "2026-01", None])
def test_manager_roster_rejects_invalid_requested_quarter(value):
    with pytest.raises(ValueError, match="quarter"):
        quarter.active_managers(managers(), value)


@pytest.mark.parametrize("column,value", [("active_from_quarter", ""),
                                         ("active_from_quarter", "2020Q5"),
                                         ("active_to_quarter", "2026Q0"),
                                         ("active_to_quarter", "2019Q4")])
def test_manager_roster_rejects_invalid_registry_intervals(column, value):
    registry = managers()
    registry.loc[0, column] = value
    with pytest.raises(ValueError, match="quarter"):
        quarter.active_managers(registry, "2026Q2")


@pytest.mark.parametrize("column,value", [("manager_id", "pershing_square"),
                                         ("manager_id", "  "),
                                         ("cik", "0001336528"),
                                         ("cik", "0"), ("cik", "123.5"), ("cik", "")])
def test_manager_roster_rejects_missing_or_duplicate_identity(column, value):
    registry = applicable_registry()
    registry.loc[1, column] = value
    with pytest.raises(ValueError, match="identity"):
        quarter.active_managers(registry, "2026Q2")


def test_manager_roster_validates_inactive_rows_and_required_columns():
    registry = applicable_registry()
    registry.loc[2, "cik"] = "001336528"
    with pytest.raises(ValueError, match="duplicate.*CIK"):
        quarter.active_managers(registry, "2026Q2")
    with pytest.raises(ValueError, match="Missing.*enabled"):
        quarter.active_managers(managers().drop(columns="enabled"), "2026Q2")


@pytest.mark.parametrize("kind", ["empty", "disabled", "future", "expired"])
def test_manager_roster_rejects_empty_applicable_cohort(kind):
    registry = managers()
    if kind == "empty":
        registry = registry.iloc[0:0]
    elif kind == "disabled":
        registry.loc[0, "enabled"] = "False"
    elif kind == "future":
        registry.loc[0, "active_from_quarter"] = "2027Q1"
    else:
        registry.loc[0, "active_to_quarter"] = "2026Q1"
    with pytest.raises(ValueError, match="No applicable managers"):
        quarter.active_managers(registry, "2026Q2")


@pytest.mark.parametrize("column,value", [("enabled", "maybe"), ("required_for_gate", "maybe"),
                                         ("manager_weight", "nan")])
def test_manager_roster_rejects_ambiguous_gate_or_nonfinite_weight(column, value):
    registry = managers()
    registry.loc[0, column] = value
    with pytest.raises(ValueError):
        quarter.active_managers(registry, "2026Q2")


def test_manager_roster_identity_is_stable_and_does_not_mutate_registry():
    registry = applicable_registry()
    before = registry.copy(deep=True)
    identity = quarter.manager_roster_identity(registry, "2026Q2")
    assert identity["quarter"] == "2026Q2"
    assert identity["applicable_manager_ids"] == ["pershing_square", "sa"]
    assert identity["applicable_manager_count"] == 2
    assert len(identity["roster_sha256"]) == 64
    pd.testing.assert_frame_equal(before, registry)
    assert identity == quarter.manager_roster_identity(registry.iloc[::-1], "2026Q2")
    registry.loc[0, "cik"] = "0001336528"
    registry.loc[0, "manager_weight"] = "1.0"
    assert identity == quarter.manager_roster_identity(registry, "2026Q2")
    registry.loc[2, "manager_weight"] = "99"
    assert identity == quarter.manager_roster_identity(registry, "2026Q2")


@pytest.mark.parametrize("column,value", [("cik", "1234568"), ("manager_weight", "3"),
                                         ("required_for_gate", "True"),
                                         ("active_from_quarter", "2024Q2"),
                                         ("active_to_quarter", "2026Q4")])
def test_manager_roster_identity_changes_with_identity_or_business_contract(column, value):
    registry = applicable_registry()
    original = quarter.manager_roster_identity(registry, "2026Q2")["roster_sha256"]
    registry.loc[1, column] = value
    assert original != quarter.manager_roster_identity(registry, "2026Q2")["roster_sha256"]


def test_filing_plan_does_not_treat_inapplicable_manager_as_missing(tmp_path):
    path = tmp_path / "applicable-submissions.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("CIK0001336528.json", json.dumps({"filings": {"recent": {}}}))
    cohort = quarter.active_managers(applicable_registry(), "2024Q2")
    plan = quarter.filing_plan(path, cohort, "2024Q2", "2024-08-15")
    assert plan.manager_id.tolist() == ["pershing_square"]
    assert plan.status.tolist() == ["MISSING_INITIAL_FILING"]


def test_pershing_alias_is_forward_only_and_filters_amendments(tmp_path):
    path = tmp_path / "submissions.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for cik, quarter_end in ((1336528, "2026-03-31"), (2026053, "2026-06-30")):
            recent = {"form": ["13F-HR/A", "13F-HR"], "reportDate": [quarter_end] * 2,
                      "accessionNumber": ["amendment", "initial"], "filingDate": ["2026-08-16", "2026-08-14"],
                      "acceptanceDateTime": ["2026-08-16T20:27:06Z", "2026-08-14T20:27:06Z"]}
            archive.writestr(f"CIK{cik:010d}.json", json.dumps({"filings": {"recent": recent}}))
    cohort = quarter.active_managers(managers(), "2026Q2")
    q2 = quarter.filing_plan(path, cohort, "2026Q2", "2026-09-04")
    assert q2.cik.tolist() == [2026053]
    assert q2.accession.tolist() == ["initial"]
    assert q2.identity_evidence_url.iloc[0] == quarter.PERSHING_NOTICE
    q1 = quarter.filing_plan(path, cohort, "2026Q1", "2026-09-04")
    assert q1.cik.tolist() == [1336528]
    early = quarter.filing_plan(path, cohort, "2026Q2", "2026-08-13")
    assert early.status.tolist() == ["MISSING_INITIAL_FILING"]


@pytest.fixture
def real_package():
    path = Path("D:/us-tech-quant-results/13f_pit_v1")
    if not path.exists():
        pytest.skip("External package source required for integration regression")
    parser = quarter.import_source(path / "scripts/build_13f_history.py", "test_13f_xml_source")
    selection = quarter.import_source(path / "scripts/v17b/integrity_rebuild_v17b.py", "test_13f_selection_source")
    return parser, selection


def filing_text(value=1234, count=1):
    return f'''<SEC-DOCUMENT>test
<ACCEPTANCE-DATETIME>20260814162706
ACCESSION NUMBER: 0001172661-26-003790
<XML><edgarSubmission><tableEntryTotal>{count}</tableEntryTotal></edgarSubmission></XML>
<XML><informationTable><infoTable><nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>037833100</cusip><value>{value}</value><shrsOrPrnAmt><sshPrnamt>10</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt></infoTable></informationTable></XML>
'''.encode()


def filing():
    return {"accession": "0001172661-26-003790", "accepted_at": pd.Timestamp("2026-08-14T20:27:06Z"),
            "filed_date": "2026-08-14"}


def test_sec_txt_acceptance_count_and_dollar_scale(real_package):
    parser, _ = real_package
    rows = quarter.parse_sec_txt(filing_text(), filing(), parser)
    assert rows[0]["value_usd"] == 1234
    with pytest.raises(ValueError, match="count mismatch"):
        quarter.parse_sec_txt(filing_text(count=2), filing(), parser)
    bad = filing()
    bad["accepted_at"] = pd.Timestamp("2026-08-14T20:00:00Z")
    with pytest.raises(ValueError, match="disagrees"):
        quarter.parse_sec_txt(filing_text(), bad, parser)


def test_selection_reuses_v17b_and_quarter_gate(real_package):
    parser, selection = real_package
    raw = pd.DataFrame([{"quarter": "2026Q2", "manager_id": "m", "manager_name": "Manager", "manager_weight": 1.0,
                         "accession_key": "a", "cusip": "037833100", "issuer_name": "APPLE INC", "title_of_class": "COM",
                         "reported_value_usd": 1234, "ssh_prnamt_type": "SH", "put_call": ""},
                        {"quarter": "2026Q2", "manager_id": "m", "manager_name": "Manager", "manager_weight": 1.0,
                         "accession_key": "a", "cusip": "037833100", "issuer_name": "APPLE INC", "title_of_class": "COM",
                         "reported_value_usd": 1000, "ssh_prnamt_type": "SH", "put_call": "CALL"}])
    filings = pd.DataFrame([{"quarter": "2026Q2", "filed_date": "2026-08-14", "report_date": "2026-06-30", "required_for_gate": True}])
    selected, universe = quarter.build_quarter(raw, filings, selection, parser)
    assert selected.reported_value_usd.tolist() == [1234]
    assert universe.effective_date.tolist() == ["2026-08-21"]


def test_merge_closes_previous_interval_in_new_copy():
    old = pd.DataFrame([{"quarter": "2026Q1", "cusip": "a", "report_date": "2026-03-31", "effective_date": "2026-05-22", "expiry_date": "", "universe_rank": 1}])
    new = pd.DataFrame([{"quarter": "2026Q2", "cusip": "b", "report_date": "2026-06-30", "effective_date": "2026-08-21", "expiry_date": "", "universe_rank": 1}])
    merged = quarter.merge_history(old, new)
    assert old.expiry_date.iloc[0] == ""
    assert merged.expiry_date.iloc[0] == pd.Timestamp("2026-08-20")
    with pytest.raises(ValueError, match="already exists"):
        quarter.merge_history(old, old)


def test_value_units_follow_filing_date_and_unverified_values_are_null():
    base = pd.DataFrame([{"quarter": "2022Q4", "manager_id": "m", "accession_key": key,
                          "cusip": key, "reported_value_usd": value}
                         for key, value in (("old", 5000.0), ("new", 5000.0), ("bad", 9999.0))])
    raw = base[["quarter", "manager_id", "accession_key", "cusip"]].copy()
    raw["source_reported_value"] = 5.0
    dates = base[["quarter", "manager_id", "accession_key"]].copy()
    dates["filing_date"] = ["2022-12-30", "2023-01-03", "2023-02-15"]
    fixed = quarter.verify_historical_values(base, raw, dates)
    assert fixed.reported_value_usd.iloc[:2].tolist() == [5000.0, 5.0]
    assert pd.isna(fixed.reported_value_usd.iloc[2])
    assert fixed.unit_status.iloc[2] == "UNVERIFIED"
    assert fixed.legacy_reported_value_usd.tolist() == [5000.0, 5000.0, 9999.0]


def test_disclosed_effective_date_includes_optional_manager_and_rejects_old_fill():
    from types import SimpleNamespace

    calls = []
    parser = SimpleNamespace(add_five_nyse_sessions=lambda date: calls.append(date) or "2025-11-21")
    selection = SimpleNamespace(
        HARD_CAP=1000,
        classify_equity=lambda *fields: (True, "SYNTHETIC"),
        aggregate_eligible_for_ranking=lambda frame: frame,
        select_top100=lambda frame: frame.assign(protected_core=False),
        build_universe=lambda selected, timing: timing,
    )
    raw = pd.DataFrame([
        {"quarter": "2025Q3", "manager_id": manager, "cusip": manager,
         "issuer_name": "Synthetic", "title_of_class": "COM", "ssh_prnamt_type": "SH", "put_call": ""}
        for manager in ("m1", "m2")
    ])
    filings = pd.DataFrame([
        {"quarter": "2025Q3", "manager_id": "m1", "report_date": "2025-09-30",
         "filed_date": "2025-11-10", "required_for_gate": True, "status": "INITIAL_FILING_IDENTIFIED"},
        {"quarter": "2025Q3", "manager_id": "m2", "report_date": "2025-09-30",
         "filed_date": "2025-11-14", "required_for_gate": False, "status": "INITIAL_FILING_IDENTIFIED"},
        {"quarter": "2025Q3", "manager_id": "m3", "report_date": "2025-09-30",
         "filed_date": None, "required_for_gate": True, "status": "MISSING_INITIAL_FILING"},
    ])
    selected, universe = quarter.build_quarter(raw, filings, selection, parser)
    assert calls == ["2025-11-14"]
    assert selected.manager_id.tolist() == ["m1", "m2"]
    assert universe.effective_date.tolist() == ["2025-11-21"]
    # Successfully parsed zero-holdings managers stay in the disclosed cohort.
    selected, _ = quarter.build_quarter(raw.iloc[[0]], filings, selection, parser)
    assert selected.manager_id.tolist() == ["m1"]
    with pytest.raises(ValueError, match="No disclosed"):
        quarter.build_quarter(raw, filings.iloc[2:], selection, parser)
    prior_quarter = raw.copy()
    prior_quarter.loc[0, "quarter"] = "2025Q2"
    with pytest.raises(ValueError, match="current quarter"):
        quarter.build_quarter(prior_quarter, filings, selection, parser)
    undisclosed_fill = raw.copy()
    undisclosed_fill.loc[1, "manager_id"] = "m3"
    with pytest.raises(ValueError, match="disclosed manager cohort"):
        quarter.build_quarter(undisclosed_fill, filings, selection, parser)


def _synthetic_refresh_run(tmp_path, monkeypatch, *, stage_raw=True, statuses=None, failure=None, zero_managers=()):
    """Stub parser/selection I/O to exercise the existing run route only."""
    from types import SimpleNamespace

    package = tmp_path / "protected_package"
    output = tmp_path / "staging"
    cache = tmp_path / "cache"
    registry_path = package / "config/manager_registry.csv"
    registry_path.parent.mkdir(parents=True)
    registry = pd.DataFrame([
        {"manager_id": manager, "manager_name": manager, "cik": str(number),
         "enabled": "True", "active_from_quarter": "2020Q1", "active_to_quarter": "",
         "top_n": "100", "protected_top_n": "20", "manager_weight": "1",
         "required_for_gate": "True" if number != 2 else "False"}
        for number, manager in enumerate(("m1", "m2", "m3"), 1)
    ])
    registry.to_csv(registry_path, index=False)
    source_paths = [package / "scripts/build_13f_history.py",
                    package / "scripts/v17b/integrity_rebuild_v17b.py"]
    for path in source_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# protected synthetic source\n", encoding="utf-8")
    submissions = tmp_path / "synthetic_submissions.zip"
    submissions.write_bytes(b"synthetic metadata; filing_plan is stubbed")
    history_path = tmp_path / "historical_universe.parquet"
    history = pd.DataFrame([{"quarter": "2025Q2", "cusip": "OLD_UNDISCLOSED_MANAGER",
                             "report_date": "2025-06-30", "effective_date": "2025-08-22",
                             "expiry_date": "", "universe_rank": 1, "aggregate_value_usd": 5000.0}])
    history.to_parquet(history_path, index=False)
    states = statuses or ["INITIAL_FILING_IDENTIFIED", "MISSING_INITIAL_FILING", "MISSING_SUBMISSION_MEMBER"]
    plan = pd.DataFrame([
        {"quarter": "2025Q3", "manager_id": manager, "manager_name": manager,
         "manager_weight": 1.0, "cik": number, "required_for_gate": number != 2,
         "report_date": "2025-09-30", "filed_date": "2025-11-14",
         "accession": f"a{number}", "source_url": f"https://example.invalid/{manager}",
         "status": states[number - 1]}
        for number, manager in enumerate(("m1", "m2", "m3"), 1)
    ])
    if stage_raw:
        for row in plan.loc[plan.status.eq("INITIAL_FILING_IDENTIFIED")].itertuples():
            path = output / "raw" / f"{row.cik}_{row.accession}.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic complete filing; parser is stubbed")

    monkeypatch.setattr(quarter, "filing_plan", lambda *args: plan.copy())
    monkeypatch.setattr(quarter, "import_source", lambda *args: SimpleNamespace())
    monkeypatch.setattr(quarter.requests, "get", lambda *args, **kwargs: pytest.fail("Network must not be called"))

    def parse(payload, filing, parser):
        if failure == "parse":
            raise ValueError("synthetic parse failure")
        if filing["manager_id"] in zero_managers:
            return []
        return [{"value_usd": 1234.0, "share_type": "SH", "cusip": filing["manager_id"],
                 "issuer_name": "Synthetic", "title_of_class": "COM", "put_call": ""}]

    monkeypatch.setattr(quarter, "parse_sec_txt", parse)
    monkeypatch.setattr(quarter, "configured_user_agent", lambda *args: "synthetic")

    def download(*args):
        if failure == "fetch":
            raise RuntimeError("synthetic fetch failure")
        pytest.fail("Download must not be called")

    monkeypatch.setattr(quarter, "download", download)
    captured = {}

    def build(raw, filings, selection, parser):
        captured["raw"] = raw.copy()
        captured["filings"] = filings.copy()
        if failure == "noeligible":
            return raw.iloc[0:0].copy(), pd.DataFrame()
        current = pd.DataFrame([{"quarter": "2025Q3", "cusip": "CURRENT_DISCLOSED",
                                 "report_date": "2025-09-30", "effective_date": "2025-11-21",
                                 "expiry_date": "", "universe_rank": 1, "aggregate_value_usd": 1234.0}])
        return raw.copy(), current

    monkeypatch.setattr(quarter, "build_quarter", build)
    monkeypatch.setattr(quarter, "normalize_historical_units",
                        lambda package, cache, historical, selection: (historical.copy(), pd.DataFrame(), {"synthetic": True}))
    protected = {path: quarter.sha256_file(path) for path in [registry_path, *source_paths]}
    args = SimpleNamespace(package_root=package, output_root=output, quarter="2025Q3",
                           as_of="2025-11-16", submissions_zip=submissions, fetch=failure == "fetch",
                           user_agent_source=source_paths[0], cache_root=cache, historical_universe=history_path)
    manifest = quarter.run(args)
    assert protected == {path: quarter.sha256_file(path) for path in protected}
    assert quarter.sha256_file(history_path) == manifest["sources"]["historical_universe"]["sha256"]
    return manifest, captured, output


def test_run_activates_disclosed_cohort_without_wait_or_old_quarter_fill(tmp_path, monkeypatch):
    manifest, captured, output = _synthetic_refresh_run(tmp_path, monkeypatch)
    assert manifest["status"] == "QUARTER_AND_HISTORY_STAGED"
    assert manifest["registered_manager_count"] == 3
    assert manifest["disclosed_manager_count"] == manifest["parsed_manager_count"] == 1
    assert manifest["excluded_undisclosed_manager_count"] == 2
    assert manifest["gaps"] == []
    assert {row["reason"] for row in manifest["ignored_managers"]} == {
        "MISSING_INITIAL_FILING", "MISSING_SUBMISSION_MEMBER"
    }
    assert manifest["missing_manager_policy"] == "EXCLUDE_UNDISCLOSED_NO_WAIT_NO_PREVIOUS_QUARTER_FILL"
    assert manifest["previous_quarter_manager_holdings_fill"] is False
    assert captured["raw"].manager_id.tolist() == captured["filings"].manager_id.tolist() == ["m1"]
    assert captured["raw"].quarter.tolist() == ["2025Q3"]
    merged = pd.read_parquet(output / "dynamic_universe.parquet")
    assert merged.loc[merged.quarter.eq("2025Q3"), "cusip"].tolist() == ["CURRENT_DISCLOSED"]
    assert merged.loc[merged.quarter.eq("2025Q2"), "cusip"].tolist() == ["OLD_UNDISCLOSED_MANAGER"]
    # Preserve the full plan as coverage evidence without treating it as holdings.
    saved_plan = pd.read_parquet(output / "filing_metadata.parquet")
    assert len(saved_plan) == 3
    assert saved_plan.status.tolist().count("INITIAL_FILING_IDENTIFIED") == 1


@pytest.mark.parametrize("failure,stage_raw,reason", [
    (None, False, "RAW_FILING_NOT_STAGED"),
    ("parse", True, "PARSE_FAILED:ValueError"),
    ("fetch", True, "FETCH_FAILED:RuntimeError"),
])
def test_identified_filing_failure_blocks_disclosed_snapshot(tmp_path, monkeypatch, failure, stage_raw, reason):
    manifest, captured, output = _synthetic_refresh_run(tmp_path, monkeypatch,
                                                       stage_raw=stage_raw, failure=failure)
    assert manifest["status"] == "INCOMPLETE_NO_UNIVERSE_ACTIVATION"
    assert manifest["disclosed_manager_count"] == 1
    assert manifest["parsed_manager_count"] == 0
    assert any(row["reason"].startswith(reason) for row in manifest["gaps"])
    assert manifest["excluded_undisclosed_manager_count"] == 2
    assert captured == {}
    assert not (output / "quarter_universe.parquet").exists()
    assert not (output / "dynamic_universe.parquet").exists()


def test_empty_disclosed_cohort_does_not_activate(tmp_path, monkeypatch):
    manifest, captured, output = _synthetic_refresh_run(
        tmp_path, monkeypatch, stage_raw=False,
        statuses=["MISSING_INITIAL_FILING", "MISSING_INITIAL_FILING", "MISSING_SUBMISSION_MEMBER"]
    )
    assert manifest["status"] == "INCOMPLETE_NO_UNIVERSE_ACTIVATION"
    assert manifest["disclosed_manager_count"] == manifest["parsed_manager_count"] == 0
    assert manifest["excluded_undisclosed_manager_count"] == 3
    assert manifest["gaps"] == []
    assert captured == {}
    assert not (output / "quarter_universe.parquet").exists()


def test_filing_plan_excludes_old_quarter_and_later_disclosures(tmp_path):
    registry = managers().iloc[[0]].copy()
    registry["manager_id"] = "synthetic"
    registry["cik"] = "1"
    cohort = quarter.active_managers(registry, "2025Q3")
    path = tmp_path / "asof_submissions.zip"
    with zipfile.ZipFile(path, "w") as archive:
        recent = {
            "form": ["13F-HR", "13F-HR"],
            "reportDate": ["2025-06-30", "2025-09-30"],
            "accessionNumber": ["prior", "later"],
            "filingDate": ["2025-08-14", "2025-11-15"],
            "acceptanceDateTime": ["2025-08-14T20:00:00Z", "2025-11-15T20:00:00Z"],
        }
        archive.writestr("CIK0000000001.json", json.dumps({"filings": {"recent": recent}}))
    missing = quarter.filing_plan(path, cohort, "2025Q3", "2025-11-14")
    assert missing.status.tolist() == ["MISSING_INITIAL_FILING"]
    assert "accession" not in missing
    disclosed = quarter.filing_plan(path, cohort, "2025Q3", "2025-11-15")
    assert disclosed.status.tolist() == ["INITIAL_FILING_IDENTIFIED"]
    assert disclosed.accession.tolist() == ["later"]


def test_declared_zero_holdings_is_complete_and_unknown_empty_is_rejected():
    from types import SimpleNamespace

    def text_at(root, name):
        return next((node.text for node in root.iter() if node.tag == name), None)

    parser = SimpleNamespace(localname=lambda tag: tag.rsplit("}", 1)[-1].lower(),
                             parse_holdings=lambda root, date: [], text_at=text_at)
    header = filing_text(count=0).split(b"<XML><informationTable>")[0]
    complete_zero = header + b"<XML><informationTable /></XML>"
    assert quarter.parse_sec_txt(complete_zero, filing(), parser) == []
    missing_declared_count = complete_zero.replace(b"<tableEntryTotal>0</tableEntryTotal>", b"")
    with pytest.raises(ValueError, match="count mismatch"):
        quarter.parse_sec_txt(missing_declared_count, filing(), parser)
    mismatched_count = complete_zero.replace(b"<tableEntryTotal>0", b"<tableEntryTotal>1")
    with pytest.raises(ValueError, match="count mismatch"):
        quarter.parse_sec_txt(mismatched_count, filing(), parser)
    malformed_xml = complete_zero.replace(b"<informationTable />", b"<informationTable>")
    with pytest.raises(quarter.ET.ParseError):
        quarter.parse_sec_txt(malformed_xml, filing(), parser)


def test_zero_holdings_manager_does_not_block_other_disclosed_holdings(tmp_path, monkeypatch):
    manifest, captured, output = _synthetic_refresh_run(
        tmp_path, monkeypatch, zero_managers=("m2",),
        statuses=["INITIAL_FILING_IDENTIFIED", "INITIAL_FILING_IDENTIFIED", "MISSING_INITIAL_FILING"]
    )
    assert manifest["status"] == "QUARTER_AND_HISTORY_STAGED"
    assert manifest["disclosed_manager_count"] == manifest["parsed_manager_count"] == 2
    assert [(row["manager_id"], row["rows"]) for row in manifest["raw_filings"]] == [("m1", 1), ("m2", 0)]
    assert captured["raw"].manager_id.tolist() == ["m1"]
    assert captured["filings"].manager_id.tolist() == ["m1", "m2"]
    assert (output / "quarter_universe.parquet").exists()


def test_all_zero_holdings_is_explicit_empty_without_activation(tmp_path, monkeypatch):
    manifest, captured, output = _synthetic_refresh_run(
        tmp_path, monkeypatch, zero_managers=("m1", "m2"),
        statuses=["INITIAL_FILING_IDENTIFIED", "INITIAL_FILING_IDENTIFIED", "MISSING_INITIAL_FILING"]
    )
    assert manifest["status"] == "EMPTY_DISCLOSED_HOLDINGS_NO_UNIVERSE_ACTIVATION"
    assert manifest["disclosed_manager_count"] == manifest["parsed_manager_count"] == 2
    assert all(row["rows"] == 0 for row in manifest["raw_filings"])
    assert manifest["gaps"] == []
    assert captured == {}
    assert (output / "raw_holdings.parquet").exists()
    assert not (output / "quarter_universe.parquet").exists()
    assert not (output / "dynamic_universe.parquet").exists()


def test_no_eligible_holdings_does_not_activate(tmp_path, monkeypatch):
    manifest, captured, output = _synthetic_refresh_run(tmp_path, monkeypatch, failure="noeligible")
    assert manifest["status"] == "NO_ELIGIBLE_HOLDINGS_NO_UNIVERSE_ACTIVATION"
    assert manifest["disclosed_manager_count"] == manifest["parsed_manager_count"] == 1
    assert captured["raw"].manager_id.tolist() == ["m1"]
    assert (output / "raw_holdings.parquet").exists()
    assert not (output / "quarter_universe.parquet").exists()
    assert not (output / "dynamic_universe.parquet").exists()
