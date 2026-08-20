"""FAST3 R35C diagnostic-only decomposition of the frozen R35B ledger."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


ROOT = Path(r"D:\us-tech-quant-results\frozen\fast3")
R35A = ROOT / "fast3_r35a_frozen_t1_t5_t6_outcome_blind_20260812T_r1"
R35B = ROOT / "fast3_r35b_frozen_oof_expected_payoff_20260812T_r1"
LEDGER = R35A / "FAST3_R35A_FROZEN_EXPECTED_PAYOFF_LEDGER.parquet"
JOINED = R35B / "FAST3_R35B_JOINED_EVALUATION_LEDGER.parquet"
SUMMARY = R35B / "FAST3_R35B_SUMMARY.json"
# R1 is retained unchanged. R2 closes reporting/percentile-rank contract gaps.
OUT = ROOT / "fast3_r35c_frozen_expected_payoff_direction_tail_20260812T_r2"
R35A_SHA = "75b80365aae546923b1a2cc2967c1f9538af0893ce45a402ff68cc7c315dbe1b"
STOP = "STOP_R35B_REPRODUCTION_MISMATCH"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool) -> None:
    if not condition:
        raise RuntimeError(STOP)


def sp(left: pd.Series, right: pd.Series) -> float:
    value = float(spearmanr(left.to_numpy(float), right.to_numpy(float)).statistic)
    if not np.isfinite(value):
        raise RuntimeError("STOP_R35C_METRIC_DOMAIN")
    return value


def fixed_deciles(frame: pd.DataFrame) -> pd.DataFrame:
    """Deterministic score-only deciles; stable keys resolve score ties."""
    if frame.empty:
        raise RuntimeError("STOP_R35C_METRIC_DOMAIN")
    ordered = frame.sort_values(
        ["expected_payoff_raw", "timestamp", "decision_key"], kind="mergesort"
    ).copy()
    ordered["within_decile"] = (
        np.arange(len(ordered)) * 10 // len(ordered) + 1
    ).astype("int8")
    return ordered


def direction_percentile_rank(frame: pd.DataFrame) -> pd.Series:
    """Average-tie percentile rank of the frozen EV, local to direction."""
    return frame.groupby("direction", observed=True)["expected_payoff_raw"].rank(
        method="average", pct=True
    )


def tail_stats(values: pd.Series) -> dict[str, float | int]:
    """Distribution diagnostics with an exact empirical worst-five-percent tail."""
    require(len(values) > 0 and bool(np.isfinite(values.to_numpy(float)).all()))
    quantiles = values.quantile(
        [.01, .05, .10, .25, .75, .90, .95, .99], interpolation="linear"
    )
    worst_count = int(np.ceil(.05 * len(values)))
    worst = values.nsmallest(worst_count, keep="first")
    return {
        "row_count": int(len(values)),
        "mean": float(values.mean()),
        "median": float(values.median()),
        "p01": float(quantiles.loc[.01]),
        "p05": float(quantiles.loc[.05]),
        "p10": float(quantiles.loc[.10]),
        "p25": float(quantiles.loc[.25]),
        "p75": float(quantiles.loc[.75]),
        "p90": float(quantiles.loc[.90]),
        "p95": float(quantiles.loc[.95]),
        "p99": float(quantiles.loc[.99]),
        "loss_rate": float(values.lt(0).mean()),
        "loss_lt_neg_1pct_rate": float(values.lt(-.01).mean()),
        "loss_lt_neg_2pct_rate": float(values.lt(-.02).mean()),
        "loss_lt_neg_5pct_rate": float(values.lt(-.05).mean()),
        "worst5_row_count": worst_count,
        "worst5_mean": float(worst.mean()),
    }


def verify_r35b_lineage(frame: pd.DataFrame, frozen: dict[str, object]) -> None:
    """Verify R35B is the frozen R35A score ledger plus its frozen raw_net20."""
    require(sha(LEDGER) == R35A_SHA)
    require(frozen.get("FAST3_R35B_STATUS") == "PASS")
    require(frozen.get("FAST3_R35B_CLASSIFICATION") == "B_PARTIAL_OR_MIXED_EXPECTED_PAYOFF_ORDERING")
    require(frozen.get("FAST3_R35B_DECISION") == "DO_NOT_OPEN_ECONOMIC_TRANSLATION_YET")
    require(frozen.get("R35B_EXPECTED_PAYOFF_ORDERING_PASS") is False)
    require(frozen.get("R35B_REALIZED_PAYOFF_NAME") == "raw_net20")
    require(frozen.get("R35A_EXPECTED_PAYOFF_LEDGER_SHA256") == R35A_SHA)
    require(int(frozen.get("R35B_JOINED_ROW_COUNT", -1)) == len(frame))

    required = {
        "decision_key", "timestamp", "direction", "fold_id", "expected_payoff_raw",
        "decile", "ev_group", "realized_payoff",
    }
    require(required.issubset(frame.columns))
    require(not frame.decision_key.duplicated().any())
    require(set(frame.direction) == {"UP", "DOWN"})
    require(set(frame.ev_group) == {"POSITIVE_EV", "NON_POSITIVE_EV"})
    require(bool(np.isfinite(frame.expected_payoff_raw.to_numpy(float)).all()))
    require(bool(np.isfinite(frame.realized_payoff.to_numpy(float)).all()))

    score_columns = [
        "decision_key", "timestamp", "direction", "fold_id", "expected_payoff_raw"
    ]
    score = pd.read_parquet(LEDGER, columns=score_columns)
    score["timestamp"] = pd.to_datetime(score.timestamp, utc=True)
    left = score.sort_values("decision_key", kind="mergesort").reset_index(drop=True)
    right = frame[score_columns].sort_values("decision_key", kind="mergesort").reset_index(drop=True)
    require(len(left) == len(right))
    for column in ("decision_key", "timestamp", "direction", "fold_id"):
        require(bool(left[column].equals(right[column])))
    require(bool(np.array_equal(
        left.expected_payoff_raw.to_numpy(), right.expected_payoff_raw.to_numpy()
    )))

    expected_groups = np.where(
        frame.expected_payoff_raw.gt(0), "POSITIVE_EV", "NON_POSITIVE_EV"
    )
    require(bool(np.array_equal(expected_groups, frame.ev_group.to_numpy())))
    reproduced = fixed_deciles(frame.drop(columns="decile"))
    require(bool(np.array_equal(reproduced.decision_key.to_numpy(), frame.decision_key.to_numpy())))
    require(bool(np.array_equal(reproduced.within_decile.to_numpy(), frame.decile.to_numpy())))


def main() -> None:
    frozen = json.loads(SUMMARY.read_text(encoding="utf-8"))
    frame = pd.read_parquet(JOINED)
    frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
    verify_r35b_lineage(frame, frozen)

    pooled = sp(frame.expected_payoff_raw, frame.realized_payoff)
    by_direction = {
        direction: part
        for direction, part in frame.groupby("direction", sort=True, observed=True)
    }
    up_spearman = sp(
        by_direction["UP"].expected_payoff_raw,
        by_direction["UP"].realized_payoff,
    )
    down_spearman = sp(
        by_direction["DOWN"].expected_payoff_raw,
        by_direction["DOWN"].realized_payoff,
    )
    decile_payoff = frame.groupby("decile", observed=True).realized_payoff.agg(
        ["mean", "median"]
    )
    ev_payoff = frame.groupby("ev_group", observed=True).realized_payoff.agg(
        ["mean", "median"]
    )
    reproduction = {
        "R35B_OOF_SPEARMAN": pooled,
        "UP_SPEARMAN": up_spearman,
        "DOWN_SPEARMAN": down_spearman,
        "D1_REALIZED_MEAN": float(decile_payoff.loc[1, "mean"]),
        "D10_REALIZED_MEAN": float(decile_payoff.loc[10, "mean"]),
        "D1_REALIZED_MEDIAN": float(decile_payoff.loc[1, "median"]),
        "D10_REALIZED_MEDIAN": float(decile_payoff.loc[10, "median"]),
        "POSITIVE_EV_REALIZED_MEAN": float(ev_payoff.loc["POSITIVE_EV", "mean"]),
        "NON_POSITIVE_EV_REALIZED_MEAN": float(ev_payoff.loc["NON_POSITIVE_EV", "mean"]),
    }
    reproduction["D10_MINUS_D1_REALIZED_MEAN"] = (
        reproduction["D10_REALIZED_MEAN"] - reproduction["D1_REALIZED_MEAN"]
    )
    reproduction["D10_MINUS_D1_REALIZED_MEDIAN"] = (
        reproduction["D10_REALIZED_MEDIAN"] - reproduction["D1_REALIZED_MEDIAN"]
    )
    reproduction["POSITIVE_MINUS_NONPOSITIVE_MEAN"] = (
        reproduction["POSITIVE_EV_REALIZED_MEAN"]
        - reproduction["NON_POSITIVE_EV_REALIZED_MEAN"]
    )
    for key, value in reproduction.items():
        require(bool(np.isclose(value, float(frozen[key]), atol=1e-15, rtol=0)))

    direction_rows: list[dict[str, object]] = []
    within_rows: list[dict[str, object]] = []
    within: dict[str, dict[str, float]] = {}
    for direction, part in by_direction.items():
        ev_quantiles = part.expected_payoff_raw.quantile(
            [.10, .50, .90], interpolation="linear"
        )
        direction_rows.append({
            "direction": direction,
            "row_count": len(part),
            "ev_mean": float(part.expected_payoff_raw.mean()),
            "ev_median": float(part.expected_payoff_raw.median()),
            "ev_p10": float(ev_quantiles.loc[.10]),
            "ev_p50": float(ev_quantiles.loc[.50]),
            "ev_p90": float(ev_quantiles.loc[.90]),
            "realized_payoff_mean": float(part.realized_payoff.mean()),
            "realized_payoff_median": float(part.realized_payoff.median()),
            "positive_ev_rate": float(part.expected_payoff_raw.gt(0).mean()),
        })
        ordered = fixed_deciles(part)
        within_table = ordered.groupby("within_decile", observed=True).agg(
            row_count=("decision_key", "size"),
            ev_mean=("expected_payoff_raw", "mean"),
            realized_payoff_mean=("realized_payoff", "mean"),
            realized_payoff_median=("realized_payoff", "median"),
        ).reset_index()
        for row in within_table.to_dict(orient="records"):
            within_rows.append({"direction": direction, **row})
        indexed = within_table.set_index("within_decile")
        within[direction] = {
            "d1_mean": float(indexed.loc[1, "realized_payoff_mean"]),
            "d1_median": float(indexed.loc[1, "realized_payoff_median"]),
            "d10_mean": float(indexed.loc[10, "realized_payoff_mean"]),
            "d10_median": float(indexed.loc[10, "realized_payoff_median"]),
            "d10_minus_d1_mean": float(
                indexed.loc[10, "realized_payoff_mean"]
                - indexed.loc[1, "realized_payoff_mean"]
            ),
            "d10_minus_d1_median": float(
                indexed.loc[10, "realized_payoff_median"]
                - indexed.loc[1, "realized_payoff_median"]
            ),
            "decile_mean_spearman": sp(
                within_table.within_decile, within_table.realized_payoff_mean
            ),
        }

    direction_table = pd.DataFrame(direction_rows)
    within_table = pd.DataFrame(within_rows)
    composition = frame.groupby(
        ["decile", "direction"], observed=True
    ).size().unstack(fill_value=0)
    composition = composition.reindex(columns=["UP", "DOWN"], fill_value=0)
    composition["row_count"] = composition.sum(axis=1)
    composition["up_share"] = composition.UP / composition.row_count
    composition["down_share"] = composition.DOWN / composition.row_count
    composition = composition.reset_index()[
        ["decile", "row_count", "UP", "DOWN", "up_share", "down_share"]
    ]
    composition.columns = [
        "decile", "row_count", "up_count", "down_count", "up_share", "down_share"
    ]
    d1_up_share = float(composition.loc[composition.decile.eq(1), "up_share"].iloc[0])
    d10_up_share = float(composition.loc[composition.decile.eq(10), "up_share"].iloc[0])
    up_share_change = d10_up_share - d1_up_share
    if up_share_change > 0:
        composition_status = "UP_SHARE_HIGHER_IN_D10_THAN_D1"
    elif up_share_change < 0:
        composition_status = "UP_SHARE_LOWER_IN_D10_THAN_D1"
    else:
        composition_status = "NO_D1_TO_D10_DIRECTION_SHARE_CHANGE"

    frame["ev_within_direction_percentile"] = direction_percentile_rank(frame)
    neutralized = sp(
        frame.ev_within_direction_percentile, frame.realized_payoff
    )

    cell_rows: list[dict[str, object]] = []
    for (fold, direction), part in frame.groupby(
        ["fold_id", "direction"], sort=True, observed=True
    ):
        ordered = fixed_deciles(part)
        group_means = ordered.groupby(
            "ev_group", observed=True
        ).realized_payoff.mean()
        require({"POSITIVE_EV", "NON_POSITIVE_EV"}.issubset(group_means.index))
        cell_rows.append({
            "fold_id": str(fold),
            "direction": direction,
            "row_count": len(ordered),
            "spearman": sp(ordered.expected_payoff_raw, ordered.realized_payoff),
            "d10_minus_d1_mean": float(
                ordered.loc[ordered.within_decile.eq(10), "realized_payoff"].mean()
                - ordered.loc[ordered.within_decile.eq(1), "realized_payoff"].mean()
            ),
            "positive_minus_non_positive_mean": float(
                group_means.loc["POSITIVE_EV"]
                - group_means.loc["NON_POSITIVE_EV"]
            ),
        })
    cell_table = pd.DataFrame(cell_rows)
    positive_cells = int(cell_table.spearman.gt(0).sum())
    negative_cells = int(cell_table.spearman.lt(0).sum())

    d1_tail = tail_stats(frame.loc[frame.decile.eq(1), "realized_payoff"])
    d10_tail = tail_stats(frame.loc[frame.decile.eq(10), "realized_payoff"])
    positive_tail = tail_stats(
        frame.loc[frame.ev_group.eq("POSITIVE_EV"), "realized_payoff"]
    )
    nonpositive_tail = tail_stats(
        frame.loc[frame.ev_group.eq("NON_POSITIVE_EV"), "realized_payoff"]
    )
    positive_up_share = float(
        frame.loc[frame.ev_group.eq("POSITIVE_EV"), "direction"].eq("UP").mean()
    )
    nonpositive_up_share = float(
        frame.loc[frame.ev_group.eq("NON_POSITIVE_EV"), "direction"].eq("UP").mean()
    )

    direction_composition_mechanism = (
        pooled > 0 and neutralized <= 0 and up_spearman <= 0 and down_spearman <= 0
    )
    weak_within_direction_mechanism = neutralized > 0 and positive_cells > 0
    tail_mechanism = (
        d10_tail["p01"] > d1_tail["p01"]
        and d10_tail["p05"] > d1_tail["p05"]
        and d10_tail["worst5_mean"] > d1_tail["worst5_mean"]
        and d10_tail["median"] < d1_tail["median"]
    )
    if direction_composition_mechanism:
        primary = "A_POOLED_ORDERING_PRIMARILY_DIRECTION_COMPOSITION"
        decision = "CLOSE_RAW_T1_T5_T6_EXPECTED_PAYOFF_SELECTION_LINE"
    elif weak_within_direction_mechanism:
        primary = "B_WEAK_WITHIN_DIRECTION_STRUCTURE_REMAINS"
        decision = "DO_NOT_USE_FOR_SELECTION_KEEP_DIAGNOSTIC_ONLY"
    elif tail_mechanism:
        primary = "C_EXPECTED_PAYOFF_ACTS_MORE_AS_TAIL_RISK_SCORE_THAN_RETURN_RANKER"
        decision = "DO_NOT_USE_AS_RAW_EXPECTED_PAYOFF_SELECTION_SCORE"
    else:
        primary = "D_NO_CLEAR_R35C_MECHANISM"
        decision = "DO_NOT_USE_FOR_SELECTION_KEEP_DIAGNOSTIC_ONLY"
    secondary = (
        "C_EXPECTED_PAYOFF_ACTS_MORE_AS_TAIL_RISK_SCORE_THAN_RETURN_RANKER"
        if tail_mechanism and not primary.startswith("C_") else "NONE"
    )

    OUT.mkdir(parents=True, exist_ok=False)
    composition.to_csv(
        OUT / "FAST3_R35C_DIRECTION_COMPOSITION_BY_DECILE.csv", index=False
    )
    direction_table.to_csv(OUT / "FAST3_R35C_DIRECTION_DIAGNOSTICS.csv", index=False)
    within_table.to_csv(
        OUT / "FAST3_R35C_WITHIN_DIRECTION_DECILES.csv", index=False
    )
    cell_table.to_csv(
        OUT / "FAST3_R35C_FOLD_DIRECTION_CELL_DIAGNOSTICS.csv", index=False
    )
    pd.DataFrame([
        {"cohort": "D1", **d1_tail},
        {"cohort": "D10", **d10_tail},
        {"cohort": "POSITIVE_EV", **positive_tail},
        {"cohort": "NON_POSITIVE_EV", **nonpositive_tail},
    ]).to_csv(OUT / "FAST3_R35C_TAIL_DIAGNOSTICS.csv", index=False)

    summary: dict[str, object] = {
        "FAST3_R35C_STATUS": "PASS",
        "FAST3_R35C_CLASSIFICATION": primary,
        "FAST3_R35C_DECISION": decision,
        "R35B_CLASSIFICATION_UNCHANGED": True,
        "R35B_FROZEN_CLASSIFICATION": frozen["FAST3_R35B_CLASSIFICATION"],
        "R35B_EXPECTED_PAYOFF_ORDERING_PASS": False,
        "R35A_EXPECTED_PAYOFF_LEDGER_SHA256": sha(LEDGER),
        "R35B_JOINED_EVALUATION_LEDGER_SHA256": sha(JOINED),
        "R35B_REPRODUCTION_STATUS": "PASS",
        **reproduction,
        "POOLED_SPEARMAN": pooled,
        "UP_SPEARMAN": up_spearman,
        "DOWN_SPEARMAN": down_spearman,
        "DIRECTION_NEUTRALIZED_SPEARMAN": neutralized,
        "DIRECTION_COMPOSITION_BY_EV_DECILE_STATUS": composition_status,
        "D1_TO_D10_UP_SHARE_CHANGE": up_share_change,
        "MAX_MINUS_MIN_UP_SHARE": float(
            composition.up_share.max() - composition.up_share.min()
        ),
        "D1_UP_SHARE": d1_up_share,
        "D1_DOWN_SHARE": 1.0 - d1_up_share,
        "D10_UP_SHARE": d10_up_share,
        "D10_DOWN_SHARE": 1.0 - d10_up_share,
        "UP_WITHIN_D1_MEAN": within["UP"]["d1_mean"],
        "UP_WITHIN_D1_MEDIAN": within["UP"]["d1_median"],
        "UP_WITHIN_D10_MEAN": within["UP"]["d10_mean"],
        "UP_WITHIN_D10_MEDIAN": within["UP"]["d10_median"],
        "UP_WITHIN_D10_MINUS_D1_MEAN": within["UP"]["d10_minus_d1_mean"],
        "UP_WITHIN_D10_MINUS_D1_MEDIAN": within["UP"]["d10_minus_d1_median"],
        "UP_WITHIN_DECILE_MEAN_SPEARMAN": within["UP"]["decile_mean_spearman"],
        "DOWN_WITHIN_D1_MEAN": within["DOWN"]["d1_mean"],
        "DOWN_WITHIN_D1_MEDIAN": within["DOWN"]["d1_median"],
        "DOWN_WITHIN_D10_MEAN": within["DOWN"]["d10_mean"],
        "DOWN_WITHIN_D10_MEDIAN": within["DOWN"]["d10_median"],
        "DOWN_WITHIN_D10_MINUS_D1_MEAN": within["DOWN"]["d10_minus_d1_mean"],
        "DOWN_WITHIN_D10_MINUS_D1_MEDIAN": within["DOWN"]["d10_minus_d1_median"],
        "DOWN_WITHIN_DECILE_MEAN_SPEARMAN": within["DOWN"]["decile_mean_spearman"],
        "POSITIVE_WITHIN_CELL_SPEARMAN_COUNT": positive_cells,
        "NEGATIVE_WITHIN_CELL_SPEARMAN_COUNT": negative_cells,
        "TOTAL_DIRECTION_FOLD_CELL_COUNT": len(cell_table),
        "D1_TAIL": d1_tail,
        "D10_TAIL": d10_tail,
        "D1_P01": d1_tail["p01"],
        "D10_P01": d10_tail["p01"],
        "D1_P05": d1_tail["p05"],
        "D10_P05": d10_tail["p05"],
        "D1_WORST5_MEAN": d1_tail["worst5_mean"],
        "D10_WORST5_MEAN": d10_tail["worst5_mean"],
        "D10_MINUS_D1_WORST5_MEAN": (
            d10_tail["worst5_mean"] - d1_tail["worst5_mean"]
        ),
        "POSITIVE_EV_UP_SHARE": positive_up_share,
        "NONPOSITIVE_EV_UP_SHARE": nonpositive_up_share,
        "POSITIVE_EV_TAIL": positive_tail,
        "NONPOSITIVE_EV_TAIL": nonpositive_tail,
        "POSITIVE_EV_P05": positive_tail["p05"],
        "NONPOSITIVE_EV_P05": nonpositive_tail["p05"],
        "POSITIVE_EV_WORST5_MEAN": positive_tail["worst5_mean"],
        "NONPOSITIVE_EV_WORST5_MEAN": nonpositive_tail["worst5_mean"],
        "PRIMARY_MECHANISM": primary,
        "SECONDARY_MECHANISM": secondary,
        "MODEL_FIT_COUNT": 0,
        "MODEL_PREDICT_CALL_COUNT": 0,
        "FAST3_BASE_MODEL_CHANGED": False,
        "FAST3_BASE_SIGNAL_CHANGED": False,
        "FAST3_TARGET_CHANGED": False,
        "FAST3_R34R_PROSPECTIVE_CHANGED": False,
        "FAST3_POSITION_SIZING_CHANGED": False,
        "BROKER_ACTION_ALLOWED": False,
    }
    for row in composition.itertuples(index=False):
        summary[f"D{row.decile}_UP_SHARE"] = float(row.up_share)
        summary[f"D{row.decile}_DOWN_SHARE"] = float(row.down_share)

    (OUT / "FAST3_R35C_SUMMARY.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for key in (
        "FAST3_R35C_STATUS", "FAST3_R35C_CLASSIFICATION", "FAST3_R35C_DECISION",
        "DIRECTION_NEUTRALIZED_SPEARMAN",
    ):
        print(f"{key}={summary[key]}")


if __name__ == "__main__":
    main()
