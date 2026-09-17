from __future__ import annotations

import importlib.util
import io
import sys
import zipfile
from pathlib import Path

import pandas as pd


SOURCE = Path(__file__).with_name("stage_sec_pit_taxonomy.py")
SPEC = importlib.util.spec_from_file_location("stage_sec_pit_taxonomy_under_test", SOURCE)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def synthetic_sub_zip() -> bytes:
    table = pd.DataFrame([
        {
            "adsh": "0001-23-000001", "cik": "1", "name": "ALPHA INC", "sic": "3571",
            "former": "", "changed": "", "form": "10-K", "period": "20221231", "fy": "2022",
            "fp": "FY", "filed": "20230201", "accepted": "20230201163000",
            "prevrpt": "0", "instance": "alpha-20221231.htm", "nciks": "1", "aciks": "",
        }
    ])
    raw = table.to_csv(sep="\t", index=False).encode()
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("sub.txt", raw)
        archive.writestr("num.txt", b"not retained")
    return target.getvalue()


def test_required_quarters_are_derived_and_pre2026() -> None:
    top = pd.DataFrame({"signal_date": [pd.Timestamp("2023-01-03"), pd.Timestamp("2025-12-29")]})
    start, end, quarters = MODULE.required_quarters(top)
    assert start == "2021q1"
    assert end == "2025q4"
    assert len(quarters) == 20


def test_sub_zip_integrity_schema_and_acceptance_timezone() -> None:
    frame, metadata = MODULE.parse_sub_zip(synthetic_sub_zip(), "2023q1")
    assert metadata["zip_integrity"] == "PASS"
    assert metadata["sub_row_count"] == 1
    assert frame.loc[0, "cik"] == 1
    assert frame.loc[0, "sic"] == 3571
    assert str(frame.loc[0, "accepted_timestamp_utc"]) == "2023-02-01 21:30:00+00:00"
    assert "num" not in "|".join(frame.columns)


def test_ff12_ff48_are_deterministic_static_mappings() -> None:
    assert MODULE.ff12(3571) == "06_BUSEQ"
    assert MODULE.ff48(3571) == "35_COMPS"
    assert MODULE.ff48(7372) == "34_BUSSV"
    assert MODULE.ff48(7373) == "35_COMPS"
    assert MODULE.ff12(6020) == "11_MONEY"
    assert MODULE.ff48(6020) == "44_BANKS"
    assert MODULE.ff12(None) == MODULE.ff48(None) == "UNKNOWN"
    assert MODULE.canonical_hash(MODULE.FF12_RANGES) == MODULE.canonical_hash(MODULE.FF12_RANGES)


def test_identity_requires_exact_corroboration_not_fuzzy(monkeypatch) -> None:
    evidence = pd.DataFrame([
        {
            "ticker": "AAA", "security_id": "CUSIP_AAA", "existing_bridge": True,
            "project_names": ["Alpha Technologies Inc"],
            "normalized_project_names": [MODULE.normalize_name("Alpha Technologies Inc")],
        },
        {
            "ticker": "BBB", "security_id": "A2_TICKER_BBB", "existing_bridge": False,
            "project_names": ["Beta Laboratories"],
            "normalized_project_names": [MODULE.normalize_name("Beta Laboratories")],
        },
    ])
    monkeypatch.setattr(MODULE, "project_identity_evidence", lambda _: evidence)
    top = pd.DataFrame({
        "signal_date": [pd.Timestamp("2023-01-03"), pd.Timestamp("2023-01-03")],
        "ticker": ["AAA", "BBB"],
    })
    sub = pd.DataFrame({"cik": pd.Series([1, 2], dtype="Int64"), "name": ["ALPHA TECHNOLOGIES INC", "BETA LABORATORY"]})
    current = pd.DataFrame({
        "cik": pd.Series([1, 2], dtype="Int64"), "ticker": ["AAA", "BBB"],
        "sec_title": ["ALPHA TECHNOLOGIES, INC.", "BETA LABORATORY"],
    })
    bridge = MODULE.build_cik_bridge(top, sub, current).set_index("ticker")
    assert bridge.loc["AAA", "mapping_confidence"] == "B_EXACT_SEC_TICKER_PLUS_NAME_CORROBORATED"
    assert bridge.loc["AAA", "cik"] == 1
    assert bridge.loc["BBB", "mapping_confidence"] == "UNRESOLVED"
    assert pd.isna(bridge.loc["BBB", "cik"])


def test_pit_sic_uses_latest_prior_acceptance_and_never_backward_fills() -> None:
    top = pd.DataFrame({
        "signal_date": [pd.Timestamp("2021-01-04"), pd.Timestamp("2023-01-03")],
        "ticker": ["AAA", "AAA"],
    })
    portfolio = pd.DataFrame({
        "execution_date": [pd.Timestamp("2021-01-05"), pd.Timestamp("2023-01-04")],
    })
    bridge = pd.DataFrame({
        "security_id": ["CUSIP_AAA"], "ticker": ["AAA"], "cik": pd.Series([1], dtype="Int64"),
        "mapping_confidence": ["B_EXACT_SEC_TICKER_PLUS_NAME_CORROBORATED"],
    })
    sub = pd.DataFrame({
        "cik": pd.Series([1, 1], dtype="Int64"), "sic": pd.Series([3571, 7372], dtype="Int64"),
        "accepted_timestamp_utc": pd.to_datetime(["2022-01-01T21:00:00Z", "2024-01-01T21:00:00Z"]),
        "adsh": ["old", "future"], "name": ["ALPHA", "ALPHA"],
    })
    result = MODULE.build_taxonomy(top, portfolio, bridge, sub).set_index("signal_date")
    assert pd.isna(result.loc[pd.Timestamp("2021-01-04"), "pit_sic"])
    assert result.loc[pd.Timestamp("2023-01-03"), "pit_sic"] == 3571
    assert result.loc[pd.Timestamp("2023-01-03"), "sic_source_adsh"] == "old"
    assert (result.execution_date > result.index).all()


def test_top20_candidate_weights_preserve_names_gross_and_contract() -> None:
    tickers = [f"T{i:02d}" for i in range(20)]
    date = pd.Timestamp("2023-01-03")
    top = pd.DataFrame({
        "signal_date": date, "ticker": tickers, "a2_prediction": list(reversed(range(20))),
    })
    taxonomy = pd.DataFrame({
        "signal_date": date, "ticker": tickers,
        "ff12": ["06_BUSEQ"] * 14 + ["11_MONEY"] * 6,
        "ff48": ["35_COMPS"] * 8 + ["36_CHIPS"] * 6 + ["44_BANKS"] * 6,
    })
    raw = MODULE.candidate_target(MODULE.Candidate("raw", "CONTROL", "RAW", None), top, taxonomy)[date]
    soft = MODULE.candidate_target(MODULE.Candidate("soft", "SIMPLE", "SOFT_FF12", 0.5), top, taxonomy)[date]
    assert set(raw) == set(soft) == set(tickers)
    assert abs(sum(soft.values()) - 1.0) <= 1e-12
    assert min(soft.values()) > 0
    raw_hhi = sum(weight * weight for weight in (14 / 20, 6 / 20))
    soft_sector = sum(soft[ticker] for ticker in tickers[:14])
    soft_hhi = soft_sector ** 2 + (1 - soft_sector) ** 2
    assert soft_hhi < raw_hhi


def test_contract_seals_and_artifact_budget() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "prices.trade_date.max() < pd.Timestamp(\"2026-01-01\")" in source
    assert "CANDIDATE_2025_READ_BEFORE_FREEZE" in source
    assert source.index("atomic_json(freeze_path, freeze)") < source.index("# One-time confirmation after the freeze artifact is durable.")
    success_artifacts = {
        "final_report.md", "sec_stage_manifest.json", "security_cik_bridge.parquet",
        "pit_sic_taxonomy.parquet", "pit_ff12_ff48_taxonomy.parquet", "trial_ledger.parquet",
        "pareto_frontier.csv", "finalist_freeze.json", "research_metadata.json", "hash_manifest.json",
    }
    assert len(success_artifacts) <= 10


def test_finalist_target_hash_accepts_timestamp_keys() -> None:
    target = {
        pd.Timestamp("2023-01-03"): {"B": 0.5, "A": 0.5},
        pd.Timestamp("2023-01-04"): {"A": 1.0},
    }
    hashable = {
        pd.Timestamp(date).isoformat(): dict(sorted(weights.items()))
        for date, weights in sorted(target.items())
    }
    assert len(MODULE.canonical_hash(hashable)) == 64


def test_mixed_fold_labels_have_a_stable_parquet_representation() -> None:
    frame = pd.DataFrame({"fold": [2023, 2024, "SELECTION_2023_2024"]})
    assert frame.fold.astype(str).tolist() == ["2023", "2024", "SELECTION_2023_2024"]
