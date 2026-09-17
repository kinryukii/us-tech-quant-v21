from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v22" / "a2_pit_sec_fundamental_acceleration_alpha_r1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("a2_sec_fundamental_test_module", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def module():
    return load_module()


def fact_row(concept: str, start: str | None, end: str, value: float, accession: str, *, form: str = "10-Q") -> dict:
    return {
        "cik": 1001, "concept": concept, "taxonomy": "us-gaap", "unit": "USD",
        "start_date": pd.to_datetime(start), "end_date": pd.Timestamp(end), "raw_value": value,
        "accession": accession, "fiscal_year": 2023, "fiscal_period": "Q1", "form": form,
        "filed_date_fact": pd.Timestamp("2023-05-01"), "frame": "",
        "source_sha256": "a" * 64, "source_url_id": "companyfacts/CIK0000001001",
    }


def synthetic_facts(accession: str = "0000001001-23-000001", *, form: str = "10-Q", multiplier: float = 1.0) -> pd.DataFrame:
    rows = []
    duration = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": (100.0, 80.0),
        "GrossProfit": (50.0, 36.0), "OperatingIncomeLoss": (30.0, 18.0),
        "NetIncomeLoss": (25.0, 15.0),
        "NetCashProvidedByUsedInOperatingActivities": (30.0, 20.0),
        "PaymentsToAcquirePropertyPlantAndEquipment": (10.0, 8.0),
        "ResearchAndDevelopmentExpense": (12.0, 8.0), "ShareBasedCompensation": (5.0, 4.0),
    }
    for concept, (current, prior) in duration.items():
        rows.append(fact_row(concept, "2023-01-01", "2023-03-31", current * multiplier, accession, form=form))
        rows.append(fact_row(concept, "2022-01-01", "2022-03-31", prior, accession, form=form))
    rows.append(fact_row("Assets", None, "2023-03-31", 200.0 * multiplier, accession, form=form))
    rows.append(fact_row("Assets", None, "2022-03-31", 180.0, accession, form=form))
    rows.append(fact_row("StockholdersEquity", None, "2023-03-31", 120.0, accession, form=form))
    rows.append(fact_row("StockholdersEquity", None, "2022-03-31", 100.0, accession, form=form))
    return pd.DataFrame(rows)


def synthetic_submission(accession: str = "0000001001-23-000001", *, form: str = "10-Q", accepted: str = "2023-05-01T20:00:00Z") -> pd.DataFrame:
    return pd.DataFrame([{
        "adsh": accession, "cik": 1001, "name": "TEST ISSUER INC", "form": form,
        "period_date": pd.Timestamp("2023-03-31"), "fy": "2023", "fp": "Q1",
        "filed_date": pd.Timestamp("2023-05-01"), "accepted_datetime": pd.Timestamp(accepted),
    }])


def test_novelty_audit_duplicate_stop_gate(module):
    frame, facts = module.novelty_audit()
    assert facts["exact_duplicate_count"] == 0
    assert facts["novel_core_feature_family_count"] >= 3
    assert "EXACT_DUPLICATE" not in set(frame.classification)


def test_bulk_zip_contract_metadata_without_extraction(module):
    path = module.CACHE_ROOT / "test_bulk_zip_contract_metadata.tmp.zip"
    assert not path.exists()
    try:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("CIK0000001001.json", b"{}")
            archive.writestr("CIK0000001002.json", b"{}")
        observed = module.zip_contract_metadata(path)
        assert observed["entries"] == 2
        assert observed["bytes"] == path.stat().st_size
        assert observed["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    finally:
        path.unlink(missing_ok=True)


def test_submission_bulk_parser_preserves_actual_acceptance(module):
    document = {
        "filings": {"recent": {
            "accessionNumber": ["0000001001-23-000001"], "form": ["10-Q"],
            "reportDate": ["2023-03-31"], "filingDate": ["2023-05-01"],
            "acceptanceDateTime": ["2023-05-01T20:00:00.000Z"],
            "primaryDocument": ["q1.htm"],
        }}
    }
    frame = module.submission_document_rows(document, 1001, "TEST ISSUER", 3571, "entry.json", "a" * 64)
    assert len(frame) == 1
    assert frame.iloc[0].accepted_datetime == pd.Timestamp("2023-05-01T20:00:00Z")
    assert frame.iloc[0].accepted_source_entry == "entry.json"
    assert frame.iloc[0].adsh == "0000001001-23-000001"


def test_resume_main_has_no_sec_network_path(module):
    source = inspect.getsource(module.main)
    assert "SecCache(" not in source
    assert "company_tickers(" not in source
    assert "fetch_companyfacts(" not in source


def test_resume_uses_exact_frozen_contract_and_mapping(module):
    concept, prereg, concept_sha, prereg_sha = module.restore_frozen_research_contract()
    assert concept_sha == module.FROZEN_CONCEPT_SHA256
    assert prereg_sha == module.FROZEN_PREREG_SHA256
    assert concept == module.concept_contract()
    assert prereg == module.preregistration(concept["contract_hash"], True)
    mapping, mapping_sha = module.load_frozen_cik_mapping()
    assert mapping_sha == module.FROZEN_MAPPING_LEDGER_SHA256
    assert mapping.cik.nunique() == 1219


def test_prefit_gate_terminal_contract(module):
    text = module.sec_bulk_prefit_block({"MODEL_FIT_ALLOWED": "FALSE"})
    assert "SEC_BULK_RESUME_PREFIT_GATE" in text
    assert "MODEL_FIT_ALLOWED=FALSE" in text


def test_cik_mapping_exact_historical_name(module):
    universe = pd.DataFrame([{
        "security_id": "CUSIP1", "cusip": "CUSIP1", "ticker": "ZZZX",
        "issuer_name": "Test Issuer Inc", "effective_start": pd.Timestamp("2023-01-01"),
        "effective_end": pd.Timestamp("2023-12-31"), "mapping_source": "TEST", "mapping_confidence": "HIGH",
    }])
    submissions = synthetic_submission()
    tickers = pd.DataFrame(columns=["cik", "ticker", "sec_title", "normalized_name"])
    mapped = module.build_cik_mapping(universe, submissions, tickers)
    assert int(mapped.iloc[0].cik) == 1001
    assert mapped.iloc[0].mapping_source == "SEC_SUBMISSION_LEGAL_NAME_EXACT_UNIQUE"
    assert pd.Timestamp(mapped.iloc[0].mapping_effective_date) == pd.Timestamp("2023-05-01")


def test_accepted_datetime_next_full_nyse_session(module):
    sessions = pd.to_datetime(["2023-05-01", "2023-05-02", "2023-05-03"])
    accepted = pd.Timestamp("2023-05-01T12:00:00", tz="America/New_York")
    assert module.next_full_nyse_session(accepted, sessions) == pd.Timestamp("2023-05-02")


def test_companyfacts_base_form_alias_uses_amendment_acceptance(module):
    sessions = pd.to_datetime(["2023-05-01", "2023-05-02", "2023-05-03"])
    states, audit = module.build_feature_states(
        synthetic_facts(form="10-Q"), synthetic_submission(form="10-Q/A"), sessions,
    )
    assert len(states) == 1
    assert states.iloc[0]["form"] == "10-Q/A"
    assert states.iloc[0].amendment_indicator == 1.0
    assert states.iloc[0].feature_effective_date == pd.Timestamp("2023-05-02")
    assert audit["companyfacts_amendment_form_alias_count"] > 0
    assert audit["companyfacts_base_form_mismatch_count"] == 0


def test_no_period_end_or_same_day_availability(module):
    sessions = pd.to_datetime(["2023-03-31", "2023-05-01", "2023-05-02"])
    states, facts = module.build_feature_states(synthetic_facts(), synthetic_submission(), sessions)
    assert len(states) == 1
    assert states.iloc[0].feature_effective_date == pd.Timestamp("2023-05-02")
    assert states.iloc[0].feature_effective_date > states.iloc[0].period_end_date
    assert facts["pit_effective_date_status"] == "PASS_STRICT_NEXT_NYSE_SESSION"


def test_no_amendment_backfill_and_accession_asof(module):
    original = synthetic_facts()
    amendment = synthetic_facts("0000001001-23-000002", form="10-Q/A", multiplier=1.2)
    submissions = pd.concat([
        synthetic_submission(),
        synthetic_submission("0000001001-23-000002", form="10-Q/A", accepted="2023-05-10T20:00:00Z"),
    ], ignore_index=True)
    sessions = pd.to_datetime(["2023-05-02", "2023-05-11", "2023-05-12"])
    states, _ = module.build_feature_states(pd.concat([original, amendment], ignore_index=True), submissions, sessions)
    assert list(states.feature_effective_date) == [pd.Timestamp("2023-05-02"), pd.Timestamp("2023-05-11")]
    pool = pd.DataFrame([
        {"signal_date": pd.Timestamp("2023-05-05"), "ticker": "ZZZX", "a2_rank": 1, "a2_prediction": 1.0, "cik": 1001},
        {"signal_date": pd.Timestamp("2023-05-12"), "ticker": "ZZZX", "a2_rank": 1, "a2_prediction": 1.0, "cik": 1001},
    ])
    attached = module.attach_features_asof(pool, states)
    assert attached.iloc[0].accession == "0000001001-23-000001"
    assert attached.iloc[1].accession == "0000001001-23-000002"


def test_unresolved_cik_remains_missing_neutral_in_asof_join(module):
    pool = pd.DataFrame([{
        "signal_date": pd.Timestamp("2023-05-05"), "ticker": "NO_CIK",
        "a2_rank": 7, "a2_prediction": 0.5, "cik": pd.NA,
    }])
    attached = module.attach_features_asof(pool, pd.DataFrame())
    assert len(attached) == 1
    assert pd.isna(attached.iloc[0].accession)
    assert pd.isna(attached.iloc[0].feature_effective_date)


def test_companyfacts_unit_consistency(module):
    payload = {
        "facts": {"us-gaap": {"Revenues": {"units": {
            "USD": [{"start": "2023-01-01", "end": "2023-03-31", "val": 100, "accn": "0000001001-23-000001", "fy": 2023, "fp": "Q1", "form": "10-Q", "filed": "2023-05-01"}],
            "EUR": [{"start": "2023-01-01", "end": "2023-03-31", "val": 90, "accn": "0000001001-23-000001", "fy": 2023, "fp": "Q1", "form": "10-Q", "filed": "2023-05-01"}],
        }}}},
    }
    records = module.companyfacts_records(json.dumps(payload).encode(), 1001, "b" * 64)
    assert len(records) == 1
    assert records.unit.eq("USD").all()


def test_concept_priority_and_same_period_yoy(module):
    records = synthetic_facts()
    records = pd.concat([
        records,
        pd.DataFrame([
            fact_row("Revenues", "2023-01-01", "2023-03-31", 999.0, "0000001001-23-000001"),
            fact_row("Revenues", "2022-01-01", "2022-03-31", 999.0, "0000001001-23-000001"),
        ]),
    ], ignore_index=True)
    current, prior = module.select_duration_pair(records, module.REVENUE_PRIORITY, pd.Timestamp("2023-03-31"), "Q1")
    assert current["concept"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert current["raw_value"] == 100.0 and prior["raw_value"] == 80.0


def test_duration_mismatch_guard(module):
    records = pd.DataFrame([
        fact_row("Revenues", "2023-01-01", "2023-03-31", 100.0, "A"),
        fact_row("Revenues", "2021-12-01", "2022-03-31", 80.0, "A"),
    ])
    current, prior = module.select_duration_pair(records, ("Revenues",), pd.Timestamp("2023-03-31"), "Q1")
    assert current is not None and prior is None


def test_denominator_guard(module):
    assert module.safe_div(10.0, 2.0) == 5.0
    assert np.isnan(module.safe_div(10.0, 0.0))
    assert np.isnan(module.safe_div(1e9, 0.5))


def test_cash_flow_capex_and_accrual_formulas(module):
    states, _ = module.build_feature_states(
        synthetic_facts(), synthetic_submission(), pd.to_datetime(["2023-05-02", "2023-05-03"])
    )
    row = states.iloc[0]
    assert row.free_cash_flow_margin == pytest.approx((30.0 - 10.0) / 100.0)
    assert row.accrual_quality == pytest.approx((25.0 - 30.0) / 200.0)


def test_2026_filing_exclusion(module):
    facts = synthetic_facts()
    submission = synthetic_submission(accepted="2026-01-02T20:00:00Z")
    states, _ = module.build_feature_states(facts, submission, pd.to_datetime(["2026-01-05"]))
    assert states.empty


def test_missing_neutral_policy_and_coverage(module):
    values = pd.Series([1.0, np.nan, 3.0])
    ranked = module.rank_z(values)
    assert ranked.iloc[1] == 0.0
    panel = pd.DataFrame({
        "signal_date": [pd.Timestamp("2023-01-01")] * 40,
        "a2_rank": range(1, 41), "feature_covered": [True] * 24 + [False] * 16,
        "ff12": ["BUSINESS"] * 40, "avg_dollar_volume_20d": range(40),
    })
    facts, _ = module.coverage_metrics(panel)
    assert facts["raw_top40_coverage_median"] == pytest.approx(0.60)
    assert facts["coverage_gate"] == "PASS"


def test_raw_top40_prior_top10_and_equal_weight_contract(module):
    rows = []
    for date in pd.to_datetime(["2022-01-03", "2022-02-01"]):
        for rank in range(1, 46):
            rows.append({
                "signal_date": date, "ticker": f"T{rank:02d}", "a2_rank": rank,
                "raw_score_z": (46 - rank) / 10.0, "model_signal": float(rank),
            })
    panel = pd.DataFrame(rows)
    targets = module.membership_targets(panel, "model_signal", 0.50, "EP1_RAW_TOP10_PROTECTED")
    assert len(targets) == 2
    for weights in targets.values():
        assert len(weights) == 20
        assert sum(weights.values()) == pytest.approx(1.0)
        assert set(f"T{rank:02d}" for rank in range(1, 11)).issubset(weights)
        assert set(weights.values()) == {0.05}


def test_share_dilution_disabled_scale_guard_and_no_promotion(module):
    contract = module.concept_contract()
    prereg = module.preregistration(contract["contract_hash"], False)
    assert contract["dilution_feature_status"] == "DISABLED_SCALE_UNSAFE"
    assert prereg["automatic_promotion"] is False
    assert prereg["moomoo_api_allowed"] is False
    assert len(prereg["models"]) <= 36


def test_artifact_hash_verification(module):
    expected = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    assert module.sha256_file(SCRIPT) == expected


def test_clean_label_and_firewall_contract_literals():
    text = SCRIPT.read_text(encoding="utf-8")
    for token in (
        "continuous_raw_counterfactual", "LABEL_CUTOFF", "PRIMARY_CHANGED_AFTER_2025_READ",
        "outer_outcome_read_count_at_freeze", "automatic_promotion", "CURRENT_HOLDINGS_UNION_RAW_A2_TOP40",
    ):
        assert token in text
