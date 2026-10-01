"""Audit r3 coordinate gaps using only already saved inputs (no model calls)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
R3 = ROOT / "test2026_stage/identity_feature_application_r1"
OUT = ROOT / "test2026_stage/r4_coordinate"
OLD = ROOT.parent / "a2_13f_learned_sizing_pre2026_test2026_r1/continuation_2026_r1"
BUILDER = Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\scripts\run_rebuild.py")
KEY = ["cusip", "title_of_class", "quarter", "signal_date"]


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1 << 20), b""):
            h.update(part)
    return h.hexdigest()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ledger_path = R3 / "FINAL_111868_CANDIDATE_INPUT_GATE.parquet"
    ledger = pd.read_parquet(ledger_path)
    assert len(ledger) == 111868 and not ledger.duplicated(KEY).any()
    gap = ledger.loc[ledger.final_input_gate.eq("UNKNOWN_FROZEN_COORDINATE_NO_OVERLAP")].copy()
    assert len(gap) == 14841 and gap.moomoo_transport_code.nunique() == 212
    assert gap.coordinate_overlap_rows.eq(0).all()
    assert gap.rehab_pass.all() and gap.lookback_121_eligible.all() and gap.has_32_finite.all()
    assert not gap.proven_lifecycle_ineligible.any() and not gap.proven_121_ineligible.any()

    initial = pd.read_csv(R3 / "CONSUMED_2026_INITIAL_ADJUSTMENT_STATE.csv")
    gap = gap.merge(initial, on="moomoo_transport_code", validate="many_to_one")
    assert len(gap) == 14841
    clean = (gap.consumed_prior_events.eq(0)
             & ~gap["2026_event_publication_time_unverified"]
             & ~gap.unexplained_raw_jump_dependency)
    assert (gap.loc[clean, "initial_alpha_2026_01_02"].eq(1.0)
            & gap.loc[clean, "initial_beta_2026_01_02"].eq(0.0)).all()

    features = pd.read_parquet(R3 / "ORIGINAL_32_FEATURES_2026_CANDIDATE_INPUT_ONLY.parquet",
                               columns=["ticker", "signal_date", "close", "volume"])
    old = pd.concat([
        pd.read_parquet(OLD / name, columns=["ticker", "trade_date", "open", "high", "low", "close", "volume"])
        for name in ("REUSED_2026_ADJUSTED_PRICE_INPUT_ONLY.parquet",
                     "SUBSCRIPTION_2026_ADJUSTED_PRICE_INPUT_ONLY.parquet")
    ], ignore_index=True).drop_duplicates(["ticker", "trade_date"])
    gap = gap.merge(features.rename(columns={"close": "r3_close", "volume": "r3_volume"}),
                    on=["ticker", "signal_date"], validate="one_to_one")
    gap = gap.merge(old.rename(columns={"trade_date": "signal_date", "close": "old_close",
                                        "volume": "old_volume", "open": "old_open",
                                        "high": "old_high", "low": "old_low"}),
                    on=["ticker", "signal_date"], how="left", validate="one_to_one")
    assert gap.old_close.notna().all()
    gap["other_saved_close_exact"] = np.isclose(gap.r3_close, gap.old_close, rtol=0, atol=1e-8)
    gap["other_saved_volume_exact"] = np.isclose(gap.r3_volume, gap.old_volume, rtol=0, atol=1e-8)
    assert (gap.loc[clean, "other_saved_close_exact"]
            & gap.loc[clean, "other_saved_volume_exact"]).all()

    # The clean interval has no applied factors since the saved Raw anchor.
    # Verify actual features' close and volume are the same units as the
    # original K_DAY/NONE/RTH Raw, independently of the r3 status string.
    binding = pd.read_csv(ROOT / "test2026_stage/fixed_window_binding/raw_source_binding.csv")
    binding = binding.set_index("code", verify_integrity=True)
    clean_codes = sorted(gap.loc[clean, "moomoo_transport_code"].unique())
    raw_checks = []
    clean_rows = gap.loc[clean, ["moomoo_transport_code", "ticker", "signal_date", "r3_close", "r3_volume"]]
    for code in clean_codes:
        source_items = json.loads(binding.loc[code, "sources"])
        parts = []
        for item in source_items:
            path = Path(item["path"])
            assert path.exists() and digest(path) == item["sha256"], path
            part = pd.read_parquet(path, columns=["code", "time_key", "open", "high", "low", "close", "volume"])
            part = part.loc[part.code.astype(str).str.upper().eq(code)].copy()
            part["signal_date"] = pd.to_datetime(part.time_key).dt.normalize()
            parts.append(part)
        raw = pd.concat(parts, ignore_index=True)
        for _, dup in raw.loc[raw.duplicated("signal_date", keep=False)].groupby("signal_date"):
            assert all(dup[field].nunique() <= 1 for field in ("open", "high", "low", "close", "volume"))
        raw = raw.sort_values("signal_date", kind="mergesort").drop_duplicates("signal_date", keep="last")
        target = clean_rows.loc[clean_rows.moomoo_transport_code.eq(code)]
        joined = target.merge(raw[["signal_date", "open", "high", "low", "close", "volume"]],
                              on="signal_date", how="left", validate="one_to_one")
        joined = joined.merge(gap.loc[clean & gap.moomoo_transport_code.eq(code),
                                      ["signal_date", "old_open", "old_high", "old_low"]],
                              on="signal_date", validate="one_to_one")
        assert len(joined) == len(target) and joined.close.notna().all()
        close_exact = np.isclose(joined.r3_close, joined.close, rtol=0, atol=1e-8)
        volume_exact = np.isclose(joined.r3_volume, joined.volume, rtol=0, atol=1e-8)
        ohl_exact = {field: np.isclose(joined[field], joined[f"old_{field}"], rtol=0, atol=1e-8)
                     for field in ("open", "high", "low")}
        assert close_exact.all() and volume_exact.all() and all(v.all() for v in ohl_exact.values()), code
        raw_checks.append({"original_code": code, "candidate_days": len(joined),
                           "first_raw_date": str(raw.signal_date.min().date()),
                           "last_raw_date": str(raw.signal_date.max().date()),
                           "raw_source_count": len(source_items),
                           "raw_source_paths": json.dumps([v["path"] for v in source_items]),
                           "raw_source_hashes": json.dumps([v["sha256"] for v in source_items]),
                           "raw_close_exact_days": int(close_exact.sum()),
                           "raw_volume_exact_days": int(volume_exact.sum()),
                           "other_saved_open_exact_days": int(ohl_exact["open"].sum()),
                           "other_saved_high_exact_days": int(ohl_exact["high"].sum()),
                           "other_saved_low_exact_days": int(ohl_exact["low"].sum())})
    raw_checks = pd.DataFrame(raw_checks)
    raw_checks.to_csv(OUT / "NO_EVENT_RAW_UNIT_VERIFICATION.csv", index=False)

    gap["coordinate_evidence_class"] = np.select([
        clean,
        gap.consumed_prior_events.eq(0) & gap.unexplained_raw_jump_dependency,
        gap.consumed_prior_events.eq(0) & gap["2026_event_publication_time_unverified"],
        gap.consumed_prior_events.gt(0) & gap["2026_event_publication_time_unverified"],
    ], ["INDEPENDENT_ORIGINAL_COORDINATE_NO_EVENT_OR_JUMP",
        "INITIAL_IDENTITY_BUT_RAW_JUMP_PENDING",
        "INITIAL_IDENTITY_2026_EVENT_VERSION_PENDING",
        "PRIOR_EVENT_CHAIN_AND_2026_EVENT_VERSION_PENDING"],
        default="PRIOR_EVENT_CHAIN_INITIAL_VERSION_PENDING")
    gap["coordinate_gap_closure_proposed"] = clean
    gap["proposed_next_status"] = np.where(clean, "INPUT_VERIFIED_COORDINATE_INDEPENDENT",
                                           "UNKNOWN_EVENT_VERSION_OR_RAW_JUMP_AFTER_COORDINATE_REVIEW")
    cols = KEY + ["ticker", "moomoo_transport_code", "transport_used", "coordinate_evidence_class",
                  "coordinate_gap_closure_proposed", "proposed_next_status", "consumed_prior_events",
                  "initial_alpha_2026_01_02", "initial_beta_2026_01_02",
                  "first_consumed_2026_event", "first_unexplained_2026_jump",
                  "2026_event_publication_time_unverified", "unexplained_raw_jump_dependency",
                  "r3_close", "r3_volume", "other_saved_close_exact", "other_saved_volume_exact"]
    gap[cols].to_parquet(OUT / "COORDINATE_14841_EXACT_CANDIDATE_MAPPING.parquet", index=False)
    by_code = gap.groupby(["moomoo_transport_code", "ticker", "cusip", "title_of_class",
                            "consumed_prior_events", "initial_alpha_2026_01_02",
                            "initial_beta_2026_01_02"], as_index=False).agg(
        candidate_days=("signal_date", "size"),
        close_exact_other_saved=("other_saved_close_exact", "sum"),
        volume_exact_other_saved=("other_saved_volume_exact", "sum"),
        proposed_closure_days=("coordinate_gap_closure_proposed", "sum"))
    by_code.to_csv(OUT / "COORDINATE_212_CODE_INITIAL_STATE.csv", index=False)
    report = {
        "r3_ledger_sha256": digest(ledger_path), "original_builder_path": str(BUILDER),
        "original_builder_sha256": digest(BUILDER),
        "r3_feature_checkpoint_sha256": digest(R3 / "ORIGINAL_32_FEATURES_2026_CANDIDATE_INPUT_ONLY.parquet"),
        "r3_no_overlap_candidate_days": len(gap), "r3_no_overlap_codes": gap.moomoo_transport_code.nunique(),
        "independent_zero_event_no_jump_proposed_closure_days": int(clean.sum()),
        "independent_zero_event_no_jump_codes": len(clean_codes),
        "raw_close_and_volume_exact_days": int(raw_checks.raw_close_exact_days.sum()),
        "other_saved_open_high_low_exact_clean_days": int(raw_checks.other_saved_open_exact_days.sum()),
        "other_saved_close_and_volume_exact_days": int((gap.other_saved_close_exact & gap.other_saved_volume_exact).sum()),
        "other_saved_close_or_volume_mismatch_days": int((~(gap.other_saved_close_exact & gap.other_saved_volume_exact)).sum()),
        "zero_prior_event_codes": int(gap.loc[gap.consumed_prior_events.eq(0), "moomoo_transport_code"].nunique()),
        "evidence_classes": gap.coordinate_evidence_class.value_counts().to_dict(),
        "method": "Original adjusted_price_frame from saved RAW K_DAY/NONE/RTH and PASS rehab uses alpha=1,beta=0,volume_scale=1 at Raw anchor, then ordered events. For proposed clean days no event has been consumed since anchor; original 32 features' close and volume equal Raw, and an older separately saved adjusted output matches both. No fitted mapping is used.",
        "limitation": "No frozen same-security row exists for these 212 codes. The Raw anchor is the earliest saved row actually consumed by the original builder; the contract must accept this per-security algorithmic anchor. Prior-event and 2026-event version clock questions remain separate. Older saved adjusted output has mismatches for some prior-event chains and cannot substitute for frozen overlap. This is a proposed coordinate gate update only, not a formal prediction or NAV.",
        "new_model_fit_calls": 0, "new_preprocessor_fit_calls": 0,
    }
    (OUT / "COORDINATE_EVIDENCE_REPORT.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("r3_no_overlap_candidate_days", "independent_zero_event_no_jump_proposed_closure_days", "evidence_classes")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
