"""FAST3 R35B: one frozen, OOF-only expected-payoff ordering evaluation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


RESULTS = Path(r"D:\us-tech-quant-results")
R35A = RESULTS / "frozen/fast3/fast3_r35a_frozen_t1_t5_t6_outcome_blind_20260812T_r1"
LEDGER = R35A / "FAST3_R35A_FROZEN_EXPECTED_PAYOFF_LEDGER.parquet"
PREREG = R35A / "FAST3_R35B_PREREGISTRATION.json"
PAYOFF_SOURCE = RESULTS / "scratch/fast3/r33d_conditional_gain_magnitude_20260811T000000Z/FAST3_R33D_T6_OOF_PREDICTIONS.parquet"
OUT = RESULTS / "frozen/fast3/fast3_r35b_frozen_oof_expected_payoff_20260812T_r1"

EXPECTED_LEDGER_SHA = "75b80365aae546923b1a2cc2967c1f9538af0893ce45a402ff68cc7c315dbe1b"
EXPECTED_PREREG_SHA = "990ae2933f876fe5a34a385b0625de1eb99e5b580827ffb2547909b9b9393416"
DEVELOPMENT_END = pd.Timestamp("2026-08-07 23:59:59+00:00")


class R35BStop(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_frame_sha256(frame: pd.DataFrame) -> str:
    """Hash index-free values, including canonical row and column order."""
    blob = frame.to_csv(index=False, lineterminator="\n", float_format="%.17g").encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def safe_spearman(left: pd.Series, right: pd.Series) -> float:
    value = float(spearmanr(left.to_numpy(float), right.to_numpy(float)).statistic)
    if not np.isfinite(value):
        raise R35BStop("STOP_INVALID_R35B_METRIC_DOMAIN")
    return value


def assign_fixed_deciles(frame: pd.DataFrame) -> pd.DataFrame:
    """Outcome-blind pooled deciles; stable keys resolve only score ties."""
    ordered = frame.sort_values(
        ["expected_payoff_raw", "timestamp", "decision_key"], kind="mergesort"
    ).copy()
    ordered["decile"] = (np.arange(len(ordered)) * 10 // len(ordered) + 1).astype("int8")
    return ordered


def quantile_diagnostics(values: pd.Series) -> dict[str, float]:
    qs = values.quantile([.01, .05, .25, .75, .95, .99], interpolation="linear")
    return {"mean": float(values.mean()), "median": float(values.median()), "std": float(values.std(ddof=1)),
            "p01": float(qs.loc[.01]), "p05": float(qs.loc[.05]), "p25": float(qs.loc[.25]),
            "p75": float(qs.loc[.75]), "p95": float(qs.loc[.95]), "p99": float(qs.loc[.99])}


def main() -> None:
    # Identity and protocol checks precede the first outcome-value read.
    if sha256_file(LEDGER) != EXPECTED_LEDGER_SHA or sha256_file(PREREG) != EXPECTED_PREREG_SHA:
        raise R35BStop("STOP_PRE_RUN_R35A_OR_R35B_IDENTITY_MISMATCH")
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if (prereg.get("SCORE") != "EXPECTED_PAYOFF_RAW"
            or prereg.get("POSITIVE_EV_THRESHOLD") != "EXPECTED_PAYOFF_RAW > 0"
            or prereg.get("OUTCOME_READ_IN_R35A") != 0):
        raise R35BStop("STOP_R35B_PREREGISTRATION_UNRESOLVED")
    # This is a target-blind, literal operationalization of the frozen phrase
    # "not single-direction-only": each observed direction must order positively.
    direction_rule = "UP_SPEARMAN>0_AND_DOWN_SPEARMAN>0"

    score = pd.read_parquet(LEDGER)
    score["timestamp"] = pd.to_datetime(score["timestamp"], utc=True)
    protected = score.timestamp.gt(DEVELOPMENT_END)
    legal_score = score.loc[~protected].copy()
    if legal_score.empty or legal_score.decision_key.duplicated().any():
        raise R35BStop("STOP_R35B_SCORE_LEDGER_INTEGRITY")

    # The filter is deliberately pushed into parquet: no protected raw_net20
    # value is materialized in this process.
    payoff = pd.read_parquet(
        PAYOFF_SOURCE,
        columns=["candidate_id", "decision_timestamp_utc", "raw_net20"],
        filters=[("decision_timestamp_utc", "<=", DEVELOPMENT_END.to_pydatetime())],
    ).rename(columns={"candidate_id": "decision_key", "raw_net20": "realized_payoff"})
    payoff["decision_timestamp_utc"] = pd.to_datetime(payoff["decision_timestamp_utc"], utc=True)
    if payoff.decision_key.duplicated().any():
        raise R35BStop("STOP_R35B_DUPLICATE_PAYOFF_KEY")
    joined = legal_score.merge(
        payoff[["decision_key", "realized_payoff"]], on="decision_key", how="left", validate="one_to_one"
    )
    if joined.realized_payoff.isna().any() or not np.isfinite(joined.realized_payoff).all():
        raise R35BStop("STOP_REALIZED_PAYOFF_CONTRACT_UNRESOLVED")
    if not joined.timestamp.le(DEVELOPMENT_END).all():
        raise R35BStop("STOP_PROTECTED_REGION_OUTCOME_READ")

    joined = assign_fixed_deciles(joined)
    joined["ev_group"] = np.where(joined.expected_payoff_raw.gt(0), "POSITIVE_EV", "NON_POSITIVE_EV")
    overall = safe_spearman(joined.expected_payoff_raw, joined.realized_payoff)
    deciles = joined.groupby("decile", observed=True).agg(
        row_count=("decision_key", "size"), ev_min=("expected_payoff_raw", "min"),
        ev_max=("expected_payoff_raw", "max"), ev_mean=("expected_payoff_raw", "mean"),
        realized_payoff_mean=("realized_payoff", "mean"), realized_payoff_median=("realized_payoff", "median"),
    ).reset_index()
    d1, d10 = deciles.iloc[0], deciles.iloc[-1]
    decile_mean_spearman = safe_spearman(deciles.ev_mean, deciles.realized_payoff_mean)
    decile_median_spearman = safe_spearman(deciles.ev_mean, deciles.realized_payoff_median)
    groups = joined.groupby("ev_group", observed=True).realized_payoff.agg(["size", "mean", "median"])
    pos, non = groups.loc["POSITIVE_EV"], groups.loc["NON_POSITIVE_EV"]

    folds = []
    for fold_id, part in joined.groupby("fold_id", sort=True, observed=True):
        pg = part.groupby("ev_group", observed=True).realized_payoff.mean()
        pd10 = part.loc[part.decile.eq(10), "realized_payoff"].mean()
        pd1 = part.loc[part.decile.eq(1), "realized_payoff"].mean()
        folds.append({"fold_id": str(fold_id), "row_count": len(part),
                      "spearman": safe_spearman(part.expected_payoff_raw, part.realized_payoff),
                      "d10_mean": float(pd10), "d1_mean": float(pd1),
                      "positive_ev_mean": float(pg.get("POSITIVE_EV", np.nan)),
                      "non_positive_ev_mean": float(pg.get("NON_POSITIVE_EV", np.nan))})
    fold_table = pd.DataFrame(folds)
    directions = []
    for direction, part in joined.groupby("direction", sort=True, observed=True):
        pg = part.groupby("ev_group", observed=True).realized_payoff.mean()
        directions.append({"direction": str(direction), "row_count": len(part),
                           "spearman": safe_spearman(part.expected_payoff_raw, part.realized_payoff),
                           "d10_minus_d1_mean": float(part.loc[part.decile.eq(10), "realized_payoff"].mean() - part.loc[part.decile.eq(1), "realized_payoff"].mean()),
                           "positive_minus_non_positive_mean": float(pg.get("POSITIVE_EV", np.nan) - pg.get("NON_POSITIVE_EV", np.nan))})
    direction_table = pd.DataFrame(directions)
    up, down = direction_table.set_index("direction").loc["UP"], direction_table.set_index("direction").loc["DOWN"]
    direction_status = "PASS_BOTH_DIRECTIONS_POSITIVE_SPEARMAN" if (up.spearman > 0 and down.spearman > 0) else "FAIL_NOT_BOTH_DIRECTIONS_POSITIVE_SPEARMAN"
    majority = int(fold_table.spearman.gt(0).sum()) > len(fold_table) / 2
    ordering_pass = bool(overall > 0 and d10.realized_payoff_mean > d1.realized_payoff_mean
                         and d10.realized_payoff_median >= d1.realized_payoff_median
                         and majority and pos["mean"] > non["mean"]
                         and direction_status.startswith("PASS"))
    if ordering_pass:
        classification, decision = "A_FROZEN_EXPECTED_PAYOFF_ORDERING_CONFIRMED", "AUTHORIZE_EXPECTED_PAYOFF_ECONOMIC_TRANSLATION_DESIGN"
    elif overall > 0:
        classification, decision = "B_PARTIAL_OR_MIXED_EXPECTED_PAYOFF_ORDERING", "DO_NOT_OPEN_ECONOMIC_TRANSLATION_YET"
    else:
        classification, decision = "C_NO_CONFIRMED_EXPECTED_PAYOFF_ORDERING", "DO_NOT_USE_T1_T5_T6_RAW_COMBINATION_FOR_SELECTION"

    OUT.mkdir(parents=True, exist_ok=False)
    deciles.to_csv(OUT / "FAST3_R35B_DECILE_TABLE.csv", index=False)
    deciles.to_parquet(OUT / "FAST3_R35B_DECILE_TABLE.parquet", index=False)
    fold_table.to_csv(OUT / "FAST3_R35B_FOLD_DIAGNOSTICS.csv", index=False)
    fold_table.to_parquet(OUT / "FAST3_R35B_FOLD_DIAGNOSTICS.parquet", index=False)
    direction_table.to_csv(OUT / "FAST3_R35B_DIRECTION_DIAGNOSTICS.csv", index=False)
    direction_table.to_parquet(OUT / "FAST3_R35B_DIRECTION_DIAGNOSTICS.parquet", index=False)
    joined[["decision_key", "timestamp", "direction", "fold_id", "expected_payoff_raw", "decile", "ev_group", "realized_payoff"]].to_parquet(OUT / "FAST3_R35B_JOINED_EVALUATION_LEDGER.parquet", index=False)
    summary = {
        "FAST3_R35B_STATUS": "PASS", "FAST3_R35B_CLASSIFICATION": classification, "FAST3_R35B_DECISION": decision,
        "R35A_EXPECTED_PAYOFF_LEDGER_SHA256": sha256_file(LEDGER), "R35B_PREREGISTRATION_SHA256": sha256_file(PREREG), "R35B_PREREGISTRATION_VERIFIED": True,
        "R35B_REALIZED_PAYOFF_NAME": "raw_net20", "R35B_REALIZED_PAYOFF_DEFINITION": "corporate-action-normalized executable net20", "R35B_REALIZED_PAYOFF_SOURCE": str(PAYOFF_SOURCE),
        "R35B_REALIZED_PAYOFF_SHA256": canonical_frame_sha256(joined.sort_values("decision_key")[["decision_key", "realized_payoff"]]),
        "R35B_LEGAL_HISTORICAL_ROW_COUNT": len(legal_score), "R35B_PROTECTED_ROW_EXCLUDED_COUNT": int(protected.sum()), "R35B_JOINED_ROW_COUNT": len(joined), "R35B_UNMATCHED_LEDGER_ROW_COUNT": 0, "R35B_DUPLICATE_PAYOFF_KEY_COUNT": 0,
        "R35B_OOF_SPEARMAN": overall, "R35B_OOF_SPEARMAN_ROW_COUNT": len(joined),
        "D1_REALIZED_MEAN": float(d1.realized_payoff_mean), "D1_REALIZED_MEDIAN": float(d1.realized_payoff_median), "D10_REALIZED_MEAN": float(d10.realized_payoff_mean), "D10_REALIZED_MEDIAN": float(d10.realized_payoff_median),
        "D10_MINUS_D1_REALIZED_MEAN": float(d10.realized_payoff_mean - d1.realized_payoff_mean), "D10_MINUS_D1_REALIZED_MEDIAN": float(d10.realized_payoff_median - d1.realized_payoff_median),
        "R35B_DECILE_MEAN_SPEARMAN": decile_mean_spearman, "R35B_DECILE_MEDIAN_SPEARMAN": decile_median_spearman,
        "POSITIVE_EV_COUNT": int(pos["size"]), "NON_POSITIVE_EV_COUNT": int(non["size"]), "POSITIVE_EV_REALIZED_MEAN": float(pos["mean"]), "NON_POSITIVE_EV_REALIZED_MEAN": float(non["mean"]), "POSITIVE_EV_REALIZED_MEDIAN": float(pos["median"]), "NON_POSITIVE_EV_REALIZED_MEDIAN": float(non["median"]), "POSITIVE_MINUS_NONPOSITIVE_MEAN": float(pos["mean"] - non["mean"]), "POSITIVE_MINUS_NONPOSITIVE_MEDIAN": float(pos["median"] - non["median"]),
        "POSITIVE_SPEARMAN_FOLD_COUNT": int(fold_table.spearman.gt(0).sum()), "TOTAL_EVALUATED_FOLD_COUNT": len(fold_table), "DIRECTION_RULE": direction_rule, "DIRECTION_ORDERING_STATUS": direction_status,
        "UP_SPEARMAN": float(up.spearman), "DOWN_SPEARMAN": float(down.spearman), "UP_D10_MINUS_D1_MEAN": float(up.d10_minus_d1_mean), "DOWN_D10_MINUS_D1_MEAN": float(down.d10_minus_d1_mean), "UP_POSITIVE_MINUS_NONPOSITIVE_MEAN": float(up.positive_minus_non_positive_mean), "DOWN_POSITIVE_MINUS_NONPOSITIVE_MEAN": float(down.positive_minus_non_positive_mean),
        "R35B_EXPECTED_PAYOFF_ORDERING_PASS": ordering_pass, "R35B_DECILE_MONOTONICITY_STATUS": "DIAGNOSTIC_ONLY", "EXPECTED_PAYOFF_DISTRIBUTION": quantile_diagnostics(joined.expected_payoff_raw), "REALIZED_PAYOFF_DISTRIBUTION": quantile_diagnostics(joined.realized_payoff), "EXPECTED_PAYOFF_POSITIVE_RATE": float(joined.expected_payoff_raw.gt(0).mean()),
        "OUTCOME_DEPENDENT_ROW_FILTER_COUNT": 0, "MODEL_FIT_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0, "POST_20260808_TARGET_READ_COUNT": 0, "POST_20260808_PAYOFF_READ_COUNT": 0,
        "FAST3_BASE_MODEL_CHANGED": False, "FAST3_BASE_SIGNAL_CHANGED": False, "FAST3_TARGET_CHANGED": False, "FAST3_R34R_PROSPECTIVE_CHANGED": False, "FAST3_POSITION_SIZING_CHANGED": False, "BROKER_ACTION_ALLOWED": False,
    }
    (OUT / "FAST3_R35B_SUMMARY.json").write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    for key in ("FAST3_R35B_STATUS", "FAST3_R35B_CLASSIFICATION", "FAST3_R35B_DECISION", "R35B_OOF_SPEARMAN", "R35B_JOINED_ROW_COUNT", "R35B_EXPECTED_PAYOFF_ORDERING_PASS"):
        print(f"{key}={summary[key]}")


if __name__ == "__main__":
    main()
