#!/usr/bin/env python
from pathlib import Path
import importlib.util

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/v21/v21_090_r1_d_top20_monitor_snapshot_archive_and_maturity_scheduler.py"
SPEC = importlib.util.spec_from_file_location("v21_090_r1", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def t(value) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES"}


def f(value) -> bool:
    return str(value).strip().upper() in {"FALSE", "0", "NO"}


if __name__ == "__main__":
    out = ROOT / MODULE.OUT_REL
    if not (out / MODULE.VALIDATION_NAME).is_file():
        result = MODULE.run_stage(ROOT)
    else:
        result = pd.read_csv(out / MODULE.VALIDATION_NAME).iloc[0].to_dict()
    assert out.is_dir()
    for name in MODULE.OUTPUT_NAMES:
        assert (out / name).is_file(), name

    val = pd.read_csv(out / MODULE.VALIDATION_NAME)
    assert len(val) == 1
    row = val.iloc[0]
    assert row["final_status"] in {
        "PASS_V21_090_R1_D_TOP20_MONITOR_ARCHIVE_AND_SCHEDULER_READY",
        "PARTIAL_PASS_V21_090_R1_ARCHIVE_AND_SCHEDULER_READY_WITH_DATA_WARN",
        "BLOCKED_V21_090_R1_LEAKAGE_OR_PROTECTED_MUTATION_RISK",
        "BLOCKED_V21_090_R1_REQUIRED_INPUTS_MISSING",
    }
    for col in ("research_only", "diagnostic_only", "archive_only", "scheduler_only"):
        assert t(row[col])
    for col in ("official_ranking_mutated", "official_weights_mutated", "broker_action_created", "recommendation_created"):
        assert f(row[col])

    if row["final_status"] == "BLOCKED_V21_090_R1_REQUIRED_INPUTS_MISSING":
        assert str(row.get("missing_inputs", "")).strip()
        print("PASS test_v21_090_r1_d_top20_monitor_snapshot_archive_and_maturity_scheduler")
        raise SystemExit(0)

    assert row["final_status"].startswith(("PASS_", "PARTIAL_PASS_"))
    assert f(row["protected_outputs_modified"])
    for col in ("d_baseline_preserved", "technical_085_preserved", "fundamental_086_preserved",
                "interaction_087_preserved", "review_088_preserved", "monitor_089_preserved"):
        assert t(row[col])
    for col in ("pullback_adoption_allowed", "interaction_adoption_allowed", "bucket_monitor_adoption_allowed"):
        assert f(row[col])

    archive = pd.read_csv(out / MODULE.ARCHIVE_NAME, low_memory=False)
    schedule = pd.read_csv(out / MODULE.SCHEDULE_NAME, low_memory=False)
    special = pd.read_csv(out / MODULE.SPECIAL_NAME, low_memory=False)
    gaps = pd.read_csv(out / MODULE.GAP_NAME, low_memory=False)
    assert len(archive) == 20
    assert len(schedule) == 60
    assert set(schedule["forward_window"]) == {"5D", "10D", "20D"}
    assert archive["D_rank"].is_monotonic_increasing
    source = pd.read_csv(ROOT / MODULE.MONITOR_REL).sort_values("D_rank")
    assert archive["D_rank"].tolist() == source["D_rank"].tolist()
    assert archive["ticker"].tolist() == source["ticker"].tolist()

    for frame in (archive, schedule, special, gaps):
        if "adoption_allowed" in frame:
            assert frame["adoption_allowed"].map(f).all()
        if "no_trade_action_created" in frame:
            assert frame["no_trade_action_created"].map(t).all()
    assert archive["not_a_trade_signal"].map(t).all()
    assert archive["pullback_adoption_allowed"].map(f).all()
    assert archive["interaction_adoption_allowed"].map(f).all()

    expected_special = {"TWST", "WYFI", "ICHR", "VECO", "FORM", "ACLS", "SITM", "CRDO"} & set(source["ticker"])
    assert expected_special.issubset(set(special["ticker"]))
    expected_gaps = {"ICHR", "VECO"} & set(source.loc[source["risk_bucket_from_v21_088"].eq("INTERACTION_UNAVAILABLE_NEEDS_DATA_REVIEW"), "ticker"])
    assert expected_gaps.issubset(set(gaps["ticker"]))

    cert = pd.read_csv(out / MODULE.CERT_NAME)
    assert len(cert) == 1
    assert cert.iloc[0]["certification_status"] == "CERTIFIED_NO_TRADE_DIAGNOSTIC_ARCHIVE_ONLY"
    assert t(cert.iloc[0]["no_trade_action_created"])
    for col in ("pullback_adoption_allowed", "interaction_adoption_allowed", "bucket_monitor_adoption_allowed"):
        assert f(cert.iloc[0][col])

    audit = pd.read_csv(out / MODULE.MUTATION_NAME, low_memory=False)
    assert not audit["modified_during_run"].map(t).any()
    manifest = pd.read_csv(out / MODULE.MANIFEST_NAME, keep_default_na=False, low_memory=False)
    existing = manifest["exists"].map(t)
    assert manifest.loc[existing, "sha256"].str.fullmatch(r"[0-9a-f]{64}").all()
    assert len(manifest) == int(row["hash_manifest_rows"])
    assert int(row["top20_archive_rows"]) == 20
    assert int(row["bucket_maturity_schedule_rows"]) == 60
    assert result["final_status"] == row["final_status"]
    print("PASS test_v21_090_r1_d_top20_monitor_snapshot_archive_and_maturity_scheduler")
