"""Read-only r5 candidate dependency inventory; never opens predictions or returns."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


R5 = Path(r"D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results\test2026\evidence_continuation_20260927_r5")
R3 = R5.parent / "identity_feature_application_20260926_r3"
OUT = Path(__file__).parent / "test2026_stage" / "r5_dependency_analysis"
KEY = ["quarter", "signal_date", "ticker", "cusip", "title_of_class", "moomoo_transport_code"]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    d = pd.read_parquet(R5 / "R5_FINAL_CANDIDATE_INPUT_GATE.parquet")
    u = d.loc[d.final_input_gate.astype(str).str.startswith("UNKNOWN")].copy()
    assert len(d) == 111868 and len(u) == 48797
    assert not u.duplicated(KEY).any()

    coord = pd.read_parquet(R5 / "evidence/coordinate/COORDINATE_10246_STRUCTURAL_ONLY_EXACT_KEY_OVERLAY.parquet")
    assert not coord.duplicated(KEY).any()
    u = u.merge(coord[KEY + ["remaining_dependency"]], on=KEY, how="left", validate="one_to_one")

    ev = pd.read_parquet(R3 / "CONSUMED_REHAB_EVENT_AUDIT.parquet")
    ev = ev.loc[(ev.audit_kind == "APPLIED_CORPORATE_ACTION") & (pd.to_datetime(ev.event_date) >= pd.Timestamp("2026-01-01"))]
    event_map = {code: np.sort(pd.to_datetime(g.event_date).drop_duplicates().to_numpy(dtype="datetime64[ns]"))
                 for code, g in ev.groupby("original_code")}
    event_counts = np.zeros(len(u), dtype=np.int16)
    for code, idx in u.groupby("moomoo_transport_code").indices.items():
        dates = event_map.get(code, np.array([], dtype="datetime64[ns]"))
        if len(dates):
            event_counts[idx] = np.searchsorted(dates, u.iloc[idx].signal_date.to_numpy(dtype="datetime64[ns]"), side="right")
    u["consumed_2026_event_date_count"] = event_counts
    # Every consumed 2026 action is a possible nested proof in the same saved
    # adjustment chain. This is an exposure graph, not a list of adjudicated failures.
    event_edges = []
    u_event = u.loc[u["2026_event_publication_time_unverified"].fillna(False).astype(bool)
                    | u.no_frozen_coordinate_overlap.fillna(False).astype(bool)]
    for code, g in u_event.groupby("moomoo_transport_code"):
        dates = event_map.get(code, np.array([], dtype="datetime64[ns]"))
        if not len(dates):
            continue
        for j, event_date in enumerate(dates):
            affected = g.loc[g.signal_date.ge(pd.Timestamp(event_date))]
            if affected.empty:
                continue
            edge = affected[KEY + ["final_input_gate"]].copy()
            edge["event_date"] = pd.Timestamp(event_date)
            edge["event_ordinal_2026"] = j + 1
            edge["first_consumed_2026_event"] = affected.first_consumed_2026_event.to_numpy()
            edge["event_clock_flag"] = affected["2026_event_publication_time_unverified"].to_numpy()
            edge["coordinate_flag"] = affected.no_frozen_coordinate_overlap.to_numpy()
            event_edges.append(edge)
    event_edges = pd.concat(event_edges, ignore_index=True) if event_edges else pd.DataFrame()
    event_edges.to_parquet(OUT / "R5_UNKNOWN_CUMULATIVE_2026_EVENT_EXPOSURES.parquet", index=False)
    event_blocks = event_edges.groupby(["moomoo_transport_code", "event_date"], as_index=False).agg(
        exposed_unknown_keys=("ticker", "size"), event_clock_flag_keys=("event_clock_flag", "sum"),
        coordinate_flag_keys=("coordinate_flag", "sum"), first_signal=("signal_date", "min"),
        last_signal=("signal_date", "max"))
    event_blocks.to_csv(OUT / "R5_CUMULATIVE_EVENT_EXPOSURE_BLOCKS.csv", index=False)
    u["event_clock_dependency"] = u["2026_event_publication_time_unverified"].fillna(False).astype(bool)
    u["coordinate_dependency"] = u.no_frozen_coordinate_overlap.fillna(False).astype(bool)
    u["jump_dependency"] = u.unexplained_raw_jump_dependency.fillna(False).astype(bool)
    u["raw_or_alias_dependency"] = u.final_input_gate.eq("UNKNOWN_RAW_REHAB_OR_ALIAS_IDENTITY")
    u["history_121_dependency"] = u.final_input_gate.eq("UNKNOWN_121_HISTORY")
    u["dependency_axis_count"] = u[["event_clock_dependency", "coordinate_dependency", "jump_dependency", "raw_or_alias_dependency", "history_121_dependency"]].sum(axis=1)
    # Some r5 flags describe upstream overlap even though the main gate names one reason.
    u["first_event_block_id"] = np.where(u.event_clock_dependency,
        u.moomoo_transport_code.astype(str) + "@" + pd.to_datetime(u.first_consumed_2026_event).dt.strftime("%Y-%m-%d").fillna("UNSPECIFIED"), "")
    u["coordinate_block_id"] = np.where(u.coordinate_dependency,
        u.moomoo_transport_code.astype(str) + ":" + u.remaining_dependency.fillna("OVERLAP_WITH_OTHER_GATE").astype(str), "")
    u["raw_identity_block_id"] = np.where(u.raw_or_alias_dependency,
        u.moomoo_transport_code.astype(str) + ":" + u.feature_error.fillna("").astype(str), "")
    u["history_121_block_id"] = np.where(u.history_121_dependency, u.moomoo_transport_code.astype(str), "")
    u["jump_block_id"] = np.where(u.jump_dependency,
        u.moomoo_transport_code.astype(str) + "@" + pd.to_datetime(u.first_unexplained_2026_jump).dt.strftime("%Y-%m-%d").fillna("UNSPECIFIED"), "")
    keep = KEY + ["final_input_gate", "first_consumed_2026_event", "first_unexplained_2026_jump",
        "event_clock_dependency", "coordinate_dependency", "jump_dependency", "raw_or_alias_dependency", "history_121_dependency",
        "remaining_dependency", "consumed_2026_event_date_count", "dependency_axis_count", "first_event_block_id",
        "coordinate_block_id", "raw_identity_block_id", "history_121_block_id", "jump_block_id", "raw_on_signal",
        "raw_121_calendar_ready", "rehab_pass", "lookback_121_eligible", "has_32_finite", "version_checked"]
    u[keep].to_parquet(OUT / "R5_UNKNOWN_48797_EXACT_KEY_DEPENDENCIES.parquet", index=False)

    axes = ["event_clock_dependency", "coordinate_dependency", "jump_dependency", "raw_or_alias_dependency", "history_121_dependency"]
    overlap = u.groupby(axes, dropna=False).agg(exact_keys=("ticker", "size"), codes=("moomoo_transport_code", "nunique"), signal_days=("signal_date", "nunique")).reset_index()
    overlap = overlap.sort_values("exact_keys", ascending=False)
    overlap.to_csv(OUT / "R5_DEPENDENCY_OVERLAP.csv", index=False)

    # A block is a common proof task, never an automatic gate transition.
    blocks = []
    for axis, field in [("event_clock", "first_event_block_id"), ("coordinate", "coordinate_block_id"),
                        ("raw_identity", "raw_identity_block_id"), ("history_121", "history_121_block_id"),
                        ("jump", "jump_block_id")]:
        part = u.loc[u[field].ne("")]
        for block_id, g in part.groupby(field):
            rows = {"axis": axis, "block_id": block_id, "touched_exact_keys": len(g),
                    "sole_axis_exact_keys": int(g.dependency_axis_count.eq(1).sum()),
                    "overlap_exact_keys": int(g.dependency_axis_count.gt(1).sum()),
                    "one_consumed_2026_event_exact_keys": int(g.consumed_2026_event_date_count.eq(1).sum()),
                    "single_event_and_single_axis_exact_keys": int((g.consumed_2026_event_date_count.eq(1) & g.dependency_axis_count.eq(1)).sum()) if axis == "event_clock" else 0,
                    "signal_days": g.signal_date.nunique(), "first_signal": g.signal_date.min().date().isoformat(),
                    "last_signal": g.signal_date.max().date().isoformat(), "codes": g.moomoo_transport_code.nunique(),
                    "main_gate_counts": json.dumps(g.final_input_gate.value_counts().to_dict(), ensure_ascii=False)}
            blocks.append(rows)
    b = pd.DataFrame(blocks).sort_values(["single_event_and_single_axis_exact_keys", "sole_axis_exact_keys", "touched_exact_keys"], ascending=False)
    b.to_csv(OUT / "R5_COMMON_PROOF_BLOCK_PRIORITY.csv", index=False)

    # Closeable-on-one-proof is only a triage bucket: saved evidence still must prove that one proof.
    one = u.loc[u.dependency_axis_count.eq(1)].copy()
    one["single_axis"] = np.select([one[x] for x in axes], ["event_clock", "coordinate", "jump", "raw_identity", "history_121"], default="unclassified")
    one[[*KEY, "final_input_gate", "single_axis", "first_event_block_id", "coordinate_block_id", "raw_identity_block_id",
         "history_121_block_id", "jump_block_id", "consumed_2026_event_date_count"]].to_parquet(
         OUT / "R5_ONE_AXIS_EXACT_KEYS_NOT_AUTOMATIC_PASS.parquet", index=False)
    summary = {"source_gate": str(R5 / "R5_FINAL_CANDIDATE_INPUT_GATE.parquet"), "candidate_rows": len(d), "unknown_rows": len(u),
               "overlap_flag_rows": int(u.dependency_axis_count.gt(1).sum()), "single_axis_rows": len(one),
               "axis_counts": {x: int(u[x].sum()) for x in axes}, "single_axis_counts": one.single_axis.value_counts().to_dict(),
               "coordinate_remaining_dependency": u.remaining_dependency.value_counts(dropna=True).to_dict(),
               "cumulative_2026_event_exposure_edges": len(event_edges),
               "formal_gate_changes": 0, "models_or_scores_read": 0, "prediction_calls": 0, "fit_calls": 0}
    (OUT / "R5_DEPENDENCY_GRAPH_SUMMARY.json").write_text(json.dumps(summary, indent=2, default=int), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=int))
    print(b.head(20)[["axis", "block_id", "touched_exact_keys", "sole_axis_exact_keys", "overlap_exact_keys"]].to_string(index=False))


if __name__ == "__main__":
    main()
