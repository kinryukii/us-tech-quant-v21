"""Read-only structural overlay for residual r3 no-overlap candidate keys."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
STAGE = ROOT / "test2026_stage"
R3 = STAGE / "identity_feature_application_r1"
OUT = STAGE / "r4_coordinate"
BUILDER = Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\scripts\run_rebuild.py")
KEY = ["cusip", "title_of_class", "quarter", "signal_date"]


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1 << 20), b""):
            h.update(part)
    return h.hexdigest()


def main() -> None:
    r3 = pd.read_parquet(R3 / "FINAL_111868_CANDIDATE_INPUT_GATE.parquet")
    prior = pd.read_parquet(OUT / "COORDINATE_14841_EXACT_CANDIDATE_MAPPING.parquet")
    residual = prior.loc[~prior.coordinate_gap_closure_proposed].copy()
    assert len(residual) == 10246 and residual.moomoo_transport_code.nunique() == 147
    assert not residual.duplicated(KEY).any()
    assert residual.transport_used.eq(residual.moomoo_transport_code).all(), "ALIAS_NEEDS_SEPARATE_IDENTITY_CHECK"
    flags = r3[KEY + ["rehab_pass", "lookback_121_eligible", "has_32_finite", "feature_error",
                      "proven_lifecycle_ineligible", "proven_121_ineligible", "raw_on_signal"]]
    residual = residual.merge(flags, on=KEY, validate="one_to_one")
    assert (residual.rehab_pass & residual.lookback_121_eligible & residual.has_32_finite
            & residual.raw_on_signal).all()
    assert residual.feature_error.fillna("").eq("").all()
    assert not residual.proven_lifecycle_ineligible.any() and not residual.proven_121_ineligible.any()

    receipt_path = STAGE / "fixed_window_raw/FIXED_WINDOW_RAW_RECEIPT.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert (receipt["kline_type"], receipt["autype"], receipt["session"]) == ("K_DAY", "NONE", "RTH")
    raw_receipt = pd.DataFrame(receipt["records"])[["code", "status", "sha256", "first_date", "last_date"]]
    raw_receipt = raw_receipt.set_index("code")
    codes = sorted(residual.moomoo_transport_code.unique())
    assert raw_receipt.loc[codes, "status"].eq("RAW_SAVED_INPUT_ONLY").all()
    binding = pd.read_csv(STAGE / "fixed_window_binding/raw_source_binding.csv").set_index("code")
    assert binding.loc[codes, "source_file_count"].ge(1).all()
    for code in codes:
        for source in json.loads(binding.loc[code, "sources"]):
            path = Path(source["path"])
            assert path.exists() and digest(path) == source["sha256"], path

    audit_path = R3 / "CONSUMED_REHAB_EVENT_AUDIT.parquet"
    events = pd.read_parquet(audit_path)
    applied = events.loc[events.audit_kind.eq("APPLIED_CORPORATE_ACTION")
                         & events.original_code.isin(codes)].copy()
    jumps = events.loc[events.audit_kind.eq("LARGE_RAW_MOVE_NO_VENDOR_EVENT")
                       & events.original_code.isin(codes)].copy()
    event_info = applied.groupby("original_code", as_index=False).agg(
        consumed_events_total=("event_date", "size"),
        first_consumed_event=("event_date", "min"),
        last_consumed_event=("event_date", "max"),
        share_events_total=("share_event", "sum"))
    before = applied.loc[applied.event_date.lt(pd.Timestamp("2026-01-02"))]
    prior_info = before.groupby("original_code", as_index=False).agg(
        prior_events=("event_date", "size"),
        prior_share_events=("share_event", "sum"),
        first_prior_event=("event_date", "min"),
        last_prior_event=("event_date", "max"))
    by_code = residual.groupby(["moomoo_transport_code", "ticker", "cusip", "title_of_class",
                                "coordinate_evidence_class", "consumed_prior_events",
                                "initial_alpha_2026_01_02", "initial_beta_2026_01_02"],
                               as_index=False).agg(
        candidate_days=("signal_date", "size"),
        first_candidate=("signal_date", "min"),
        last_candidate=("signal_date", "max"),
        old_adjusted_close_exact=("other_saved_close_exact", "sum"),
        old_adjusted_volume_exact=("other_saved_volume_exact", "sum"))
    by_code = by_code.merge(event_info, left_on="moomoo_transport_code", right_on="original_code",
                            how="left", validate="many_to_one")
    by_code = by_code.merge(prior_info, left_on="moomoo_transport_code", right_on="original_code",
                            how="left", suffixes=("", "_prior"), validate="many_to_one")
    by_code = by_code.merge(raw_receipt.reset_index().rename(columns={"code": "moomoo_transport_code",
                                                                 "sha256": "current_raw_sha256"}),
                            on="moomoo_transport_code", validate="many_to_one")
    by_code["raw_source_paths_and_hashes"] = by_code.moomoo_transport_code.map(
        lambda code: binding.loc[code, "sources"])
    by_code["original_frozen_overlap_rows"] = 0
    by_code["same_original_builder_and_raw_unit_structural_check"] = True
    by_code["historical_rehab_version_at_signal_proven"] = False
    by_code["candidate_gate_closure"] = False
    by_code["missing_evidence"] = np.select([
        by_code.coordinate_evidence_class.eq("INITIAL_IDENTITY_BUT_RAW_JUMP_PENDING"),
        by_code.coordinate_evidence_class.eq("INITIAL_IDENTITY_2026_EVENT_VERSION_PENDING"),
        by_code.coordinate_evidence_class.eq("PRIOR_EVENT_CHAIN_INITIAL_VERSION_PENDING"),
    ], ["Original supplier correction or security/event evidence explaining raw jump before affected signals",
        "Historical 2026 event amount, reference price, and original supplier factor version before affected signals",
        "Historical pre-2026 event factors and original supplier version establishing initial alpha/beta before 2026 signals"],
        default="Historical pre-2026 initial event chain and consumed 2026 event factor versions before affected signals")
    by_code.to_csv(OUT / "COORDINATE_147_CODE_RESIDUAL_SOURCE_AND_CHAIN.csv", index=False)

    residual["same_original_builder_and_raw_unit_structural_check"] = True
    residual["historical_version_or_jump_verified"] = False
    residual["candidate_gate_closure"] = False
    residual["remaining_dependency"] = np.select([
        residual.coordinate_evidence_class.eq("INITIAL_IDENTITY_BUT_RAW_JUMP_PENDING"),
        residual.coordinate_evidence_class.eq("INITIAL_IDENTITY_2026_EVENT_VERSION_PENDING"),
        residual.coordinate_evidence_class.eq("PRIOR_EVENT_CHAIN_INITIAL_VERSION_PENDING"),
    ], ["UNEXPLAINED_RAW_JUMP", "2026_EVENT_VERSION_CLOCK", "INITIAL_PRE2026_EVENT_VERSION"],
        default="INITIAL_PRE2026_AND_2026_EVENT_VERSIONS")
    assert len(residual) == 10246
    residual[KEY + ["ticker", "moomoo_transport_code", "coordinate_evidence_class",
                    "same_original_builder_and_raw_unit_structural_check",
                    "historical_version_or_jump_verified", "candidate_gate_closure",
                    "remaining_dependency", "consumed_prior_events", "initial_alpha_2026_01_02",
                    "initial_beta_2026_01_02", "first_consumed_2026_event",
                    "first_unexplained_2026_jump"]].to_parquet(
                        OUT / "COORDINATE_10246_STRUCTURAL_ONLY_EXACT_KEY_OVERLAY.parquet", index=False)
    old_frozen = pd.read_parquet(ROOT / "results/pre2026_original_price_coordinate.parquet",
                                 columns=["ticker"])
    assert not set(residual.ticker).intersection(set(old_frozen.ticker))
    report = {
        "residual_candidate_days": len(residual), "residual_codes": len(codes),
        "source_receipt_sha256": digest(receipt_path), "rehab_audit_sha256": digest(audit_path),
        "builder_sha256": digest(BUILDER), "raw_code_status": "All 147 codes RAW_SAVED_INPUT_ONLY K_DAY/NONE/RTH; all bound Raw files SHA checked",
        "original_frozen_ticker_overlap": 0,
        "all_candidate_days_original_121_and_32_finite": True,
        "remaining_dependencies": residual.remaining_dependency.value_counts().to_dict(),
        "new_full_candidate_gate_closures_from_existing_evidence": 0,
        "interpretation": "The original builder's structural coordinate formula and Raw units can be verified, but no saved original pre-2026 price rows exist for these securities and original event-version timing or raw-jump evidence remains unresolved. This structural overlay does not authorize changing any candidate's primary UNKNOWN status to PASS.",
        "model_fit_calls": 0, "preprocessor_fit_calls": 0,
    }
    (OUT / "COORDINATE_10246_RESIDUAL_REPORT.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"days": len(residual), "codes": len(codes),
                      "remaining_dependencies": report["remaining_dependencies"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
