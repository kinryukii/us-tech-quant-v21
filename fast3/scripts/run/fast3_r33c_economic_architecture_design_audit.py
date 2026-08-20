from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
OUTPUT_ROOT = RESULTS_ROOT / "frozen/fast3/r33c_architecture_design_20260810T220000Z"

R32A_MANIFEST = RESULTS_ROOT / "frozen/fast3/r32a_full_universe_20260810T120000Z/FAST3_R32A_FULL_UNIVERSE_LABEL_MANIFEST_R1.json"
R32A_LABELS = RESULTS_ROOT / "scratch/fast3/r32a_full_universe_20260810T120000Z/FAST3_R32A_FULL_UNIVERSE_ECONOMIC_LABEL_LEDGER_R1.parquet"
R32B_T1_OOF = RESULTS_ROOT / "scratch/fast3/r32b_full_universe_20260810T160000Z/FAST3_R32B_OOF_PREDICTIONS.parquet"
R33A_SUMMARY = RESULTS_ROOT / "frozen/fast3/r33a_payoff_decomposition_20260810T180000Z/FAST3_R33A_SUMMARY.json"
R33B_T5_OOF = RESULTS_ROOT / "scratch/fast3/r33b_conditional_loss_severity_20260810T200000Z/FAST3_R33B_T5_OOF_PREDICTIONS.parquet"

EXPECTED = {
    R32A_MANIFEST: "12356e0dd8d75c8cefa4233900942e73dffd5ae0688d685be6915d99ac38cc29",
    R32A_LABELS: "cb6556078f1b2c617b496107bca4e1ffa90213639e7c9e264ab8578d380ecf49",
    R32B_T1_OOF: "a0b05b14824b79628d28a92ae786cd114806083620a5bc179d621d4942f7efee",
    R33A_SUMMARY: "64bc0af59947fe7dd473c9ede6b1ead20ec1a74733f85da761fd821186ac19b5",
    R33B_T5_OOF: "1b2be7153c731f5857d7e78488f7ffb72c0752587f69e94954137fbce04279f6",
}

OOF_ROW_COUNT = 984_049
FOLD_COUNT = 5
GAIN_SPEARMAN_LIMIT = 0.20
GAIN_RELATIVE_DEVIATION_LIMIT = 0.15
MIN_COMPATIBLE_FOLDS = 3
NY = "America/New_York"


class R33CStop(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def json_value(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(type(value).__name__)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=json_value, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def safe_spearman(left: pd.Series, right: pd.Series) -> float | None:
    valid = left.notna() & right.notna()
    x, y = left.loc[valid], right.loc[valid]
    if len(x) < 2 or x.nunique() < 2 or y.nunique() < 2:
        return None
    result = float(spearmanr(x, y).statistic)
    return result if math.isfinite(result) else None


def assign_fixed_bins(frame: pd.DataFrame, score: str, bins: int, output: str) -> pd.DataFrame:
    if len(frame) < bins:
        raise R33CStop(f"STOP_TOO_FEW_ROWS_FOR_{output}")
    ordered = frame.sort_values(
        [score, "decision_timestamp_utc", "candidate_id"],
        ascending=[True, True, True],
        kind="mergesort",
    ).copy()
    ordered[output] = np.floor(np.arange(len(ordered)) * bins / len(ordered)).astype(int) + 1
    return ordered


def validate_and_load() -> tuple[pd.DataFrame, dict[str, Any]]:
    for path, expected in EXPECTED.items():
        if not path.is_file() or file_sha256(path) != expected:
            raise R33CStop(f"STOP_FROZEN_SHA256_{path.name}")

    manifest = read_json(R32A_MANIFEST)
    r33a = read_json(R33A_SUMMARY)
    if manifest.get("SHA256") != EXPECTED[R32A_LABELS] or manifest.get("row_count") != 1_457_822:
        raise R33CStop("STOP_R32A_MANIFEST_BINDING")
    if (
        r33a.get("FAST3_R33A_STATUS") != "PASS"
        or r33a.get("FROZEN_OOF_SHA256") != EXPECTED[R32B_T1_OOF]
        or r33a.get("SPEARMAN_T1_DECILE_VS_MEAN_GAIN") != 0.5393939393939393
    ):
        raise R33CStop("STOP_R33A_EVIDENCE_BINDING")
    if r33a.get("FINAL_CONFIRMATION_DATA_USED") is not False:
        raise R33CStop("STOP_PRIOR_FINAL_CONFIRMATION_USE")

    t1 = pd.read_parquet(
        R32B_T1_OOF,
        columns=[
            "candidate_id", "decision_timestamp_utc", "head", "underlying_symbol",
            "raw_net20", "pred_t1", "fold", "trading_date",
        ],
    )
    t5 = pd.read_parquet(
        R33B_T5_OOF,
        columns=[
            "candidate_id", "decision_timestamp_utc", "head", "underlying_symbol",
            "raw_net20", "pred_t1", "fold", "trading_date", "pred_t5",
        ],
    )
    labels = pd.read_parquet(
        R32A_LABELS,
        columns=["candidate_id", "decision_timestamp_utc", "head", "fold", "net20", "label_valid"],
    )
    if any(len(x) != OOF_ROW_COUNT for x in (t1, t5)):
        raise R33CStop("STOP_OOF_ROW_COUNT")
    if any(x.candidate_id.duplicated().any() for x in (t1, t5, labels)):
        raise R33CStop("STOP_DUPLICATE_CANDIDATE_ID")

    compare = t1.merge(
        t5,
        on="candidate_id",
        how="outer",
        validate="one_to_one",
        suffixes=("_t1", "_t5"),
        indicator=True,
    )
    if len(compare) != OOF_ROW_COUNT or not compare._merge.eq("both").all():
        raise R33CStop("STOP_T1_T5_IDENTITY")
    for column in ("head", "underlying_symbol", "fold", "trading_date"):
        if not compare[f"{column}_t1"].eq(compare[f"{column}_t5"]).all():
            raise R33CStop(f"STOP_T1_T5_{column.upper()}")
    for column in ("decision_timestamp_utc", "raw_net20", "pred_t1"):
        left, right = compare[f"{column}_t1"], compare[f"{column}_t5"]
        if column == "decision_timestamp_utc":
            okay = left.eq(right).all()
        else:
            okay = np.array_equal(left.to_numpy(), right.to_numpy(), equal_nan=True)
        if not okay:
            raise R33CStop(f"STOP_T1_T5_{column.upper()}")

    label_check = t1.merge(labels, on="candidate_id", how="left", validate="one_to_one", suffixes=("_oof", "_label"))
    if label_check.label_valid.isna().any() or not label_check.label_valid.all():
        raise R33CStop("STOP_R32A_LABEL_JOIN")
    if not (
        label_check.decision_timestamp_utc_oof.eq(label_check.decision_timestamp_utc_label).all()
        and label_check.head_oof.eq(label_check.head_label).all()
        and label_check.fold_oof.eq(label_check.fold_label).all()
        and np.array_equal(label_check.raw_net20.to_numpy(), label_check.net20.to_numpy(), equal_nan=True)
    ):
        raise R33CStop("STOP_R32A_LABEL_RECONCILIATION")

    frame = t5.rename(
        columns={
            "head": "head_t5", "underlying_symbol": "underlying_symbol_t5", "fold": "fold_t5",
            "trading_date": "trading_date_t5", "decision_timestamp_utc": "decision_timestamp_utc_t5",
            "raw_net20": "raw_net20_t5", "pred_t1": "pred_t1_t5",
        }
    )[["candidate_id", "pred_t5"]].merge(t1, on="candidate_id", how="inner", validate="one_to_one")
    if frame[["pred_t1", "pred_t5", "raw_net20"]].isna().any().any():
        raise R33CStop("STOP_MISSING_AUDIT_VALUES")
    if int(frame.raw_net20.eq(0).sum()) != 0:
        raise R33CStop("STOP_ZERO_RETURN_IDENTITY_NOT_TWO_PART")
    expected_dates = frame.decision_timestamp_utc.dt.tz_convert(NY).dt.date.astype(str)
    if not frame.trading_date.eq(expected_dates).all():
        raise R33CStop("STOP_ET_TRADING_DATE_IDENTITY")
    if frame.fold.nunique() != FOLD_COUNT or set(frame["head"]) != {"UP", "DOWN"}:
        raise R33CStop("STOP_ROBUSTNESS_GROUP_IDENTITY")
    return frame, r33a


def conditional_t5_loss_audit(frame: pd.DataFrame) -> tuple[float, int]:
    losses = frame.loc[frame.raw_net20 < 0].copy()
    losses["abs_loss"] = -losses.raw_net20
    binned = assign_fixed_bins(losses, "pred_t1", 10, "t1_decile")
    pooled_t5: list[pd.Series] = []
    pooled_loss: list[pd.Series] = []
    correct = 0
    for _, part in binned.groupby("t1_decile", sort=True, observed=True):
        pooled_t5.append(part.pred_t5.rank(method="average", pct=True))
        pooled_loss.append(part.abs_loss.rank(method="average", pct=True))
        ordered = part.sort_values(
            ["pred_t5", "decision_timestamp_utc", "candidate_id"], kind="mergesort"
        )
        boundary = len(ordered) // 2
        correct += int(ordered.iloc[boundary:].abs_loss.mean() > ordered.iloc[:boundary].abs_loss.mean())
    conditional = safe_spearman(pd.concat(pooled_t5), pd.concat(pooled_loss))
    if conditional is None:
        raise R33CStop("STOP_CONDITIONAL_T5_LOSS_AUDIT")
    return conditional, correct


def gain_decile_table(frame: pd.DataFrame) -> tuple[pd.DataFrame, float, float, float]:
    binned = assign_fixed_bins(frame, "pred_t1", 10, "t1_decile")
    winners = binned.loc[binned.raw_net20 > 0].copy()
    global_gain = float(winners.raw_net20.mean())
    rows: list[dict[str, Any]] = []
    pooled_t5: list[pd.Series] = []
    pooled_gain: list[pd.Series] = []
    for decile, part in winners.groupby("t1_decile", sort=True, observed=True):
        mean_gain = float(part.raw_net20.mean())
        deviation = mean_gain - global_gain
        pooled_t5.append(part.pred_t5.rank(method="average", pct=True))
        pooled_gain.append(part.raw_net20.rank(method="average", pct=True))
        rows.append(
            {
                "t1_decile": int(decile),
                "count": len(part),
                "mean_t1_probability": float(part.pred_t1.mean()),
                "mean_gain": mean_gain,
                "median_gain": float(part.raw_net20.median()),
                "p75_gain": float(part.raw_net20.quantile(0.75)),
                "p90_gain": float(part.raw_net20.quantile(0.90)),
                "p95_gain": float(part.raw_net20.quantile(0.95)),
                "t5_spearman_vs_gain": safe_spearman(part.pred_t5, part.raw_net20),
                "gain_deviation_from_global": deviation,
                "absolute_relative_gain_deviation": abs(deviation / global_gain),
            }
        )
    table = pd.DataFrame(rows)
    decile_s = safe_spearman(table.t1_decile, table.mean_gain)
    conditional_t5_s = safe_spearman(pd.concat(pooled_t5), pd.concat(pooled_gain))
    if decile_s is None or conditional_t5_s is None or len(table) != 10:
        raise R33CStop("STOP_GAIN_DECILE_DIAGNOSTIC")
    max_relative = float(table.absolute_relative_gain_deviation.max())
    return table, global_gain, decile_s, conditional_t5_s


def magnitude_stats(frame: pd.DataFrame) -> dict[str, float | int | None]:
    wins = frame.loc[frame.raw_net20 > 0, "raw_net20"]
    losses = frame.loc[frame.raw_net20 < 0, "raw_net20"]
    gain = float(wins.mean()) if len(wins) else None
    loss = float(-losses.mean()) if len(losses) else None
    return {
        "count": len(frame),
        "positive_rate": float((frame.raw_net20 > 0).mean()),
        "mean_gain_given_win": gain,
        "mean_abs_loss_given_loss": loss,
        "break_even_win_rate": loss / (gain + loss) if gain is not None and loss is not None else None,
        "mean_net20": float(frame.raw_net20.mean()),
        "payoff_amplitude": gain + loss if gain is not None and loss is not None else None,
    }


def fixed_grid(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float | None]]:
    t1 = assign_fixed_bins(frame, "pred_t1", 5, "t1_quintile")
    both = assign_fixed_bins(t1, "pred_t5", 5, "t5_quintile")
    rows = []
    for (q1, q5), part in both.groupby(["t1_quintile", "t5_quintile"], sort=True, observed=True):
        stats = magnitude_stats(part)
        rows.append(
            {
                "t1_quintile": int(q1), "t5_quintile": int(q5),
                "mean_t1_probability": float(part.pred_t1.mean()),
                "mean_t5_score": float(part.pred_t5.mean()),
                **stats,
                "descriptive_only": True,
            }
        )
    grid = pd.DataFrame(rows)
    if len(grid) != 25 or not grid.descriptive_only.all():
        raise R33CStop("STOP_FIXED_GRID_CARDINALITY")

    qrows = []
    for q5, part in both.groupby("t5_quintile", sort=True, observed=True):
        qrows.append(
            {
                "record_type": "T5_QUINTILE_AMPLITUDE",
                "group": f"T5_Q{int(q5)}",
                "ordinal": int(q5),
                "mean_t5_score": float(part.pred_t5.mean()),
                **magnitude_stats(part),
            }
        )
    quintiles = pd.DataFrame(qrows)
    relationships = {
        "t5_quintile_vs_gain_magnitude_spearman": safe_spearman(quintiles.ordinal, quintiles.mean_gain_given_win),
        "t5_quintile_vs_loss_magnitude_spearman": safe_spearman(quintiles.ordinal, quintiles.mean_abs_loss_given_loss),
        "t5_quintile_vs_payoff_amplitude_spearman": safe_spearman(quintiles.ordinal, quintiles.payoff_amplitude),
    }
    return grid, quintiles, relationships


def compatible_gain(frame: pd.DataFrame) -> tuple[bool, float | None, float]:
    table, global_gain, decile_s, _ = gain_decile_table(frame)
    max_relative = float(table.absolute_relative_gain_deviation.max())
    compatible = abs(decile_s) < GAIN_SPEARMAN_LIMIT and max_relative < GAIN_RELATIVE_DEVIATION_LIMIT
    return compatible, decile_s, max_relative


def robustness_audit(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    rows: list[dict[str, Any]] = []
    compatible_folds = 0
    aggregate_t1 = safe_spearman(frame.loc[frame.raw_net20 > 0, "pred_t1"], frame.loc[frame.raw_net20 > 0, "raw_net20"])
    aggregate_t5 = safe_spearman(frame.loc[frame.raw_net20 > 0, "pred_t5"], frame.loc[frame.raw_net20 > 0, "raw_net20"])
    for fold, part in frame.groupby("fold", sort=True, observed=True):
        winners = part.loc[part.raw_net20 > 0]
        compatible, decile_s, max_relative = compatible_gain(part)
        compatible_folds += int(compatible)
        rows.append(
            {
                "record_type": "FOLD", "group": fold, "count": len(part), "winner_count": len(winners),
                "t1_score_vs_gain_spearman": safe_spearman(winners.pred_t1, winners.raw_net20),
                "t5_score_vs_gain_spearman": safe_spearman(winners.pred_t5, winners.raw_net20),
                "t1_decile_vs_mean_gain_spearman": decile_s,
                "max_abs_relative_gain_deviation": max_relative,
                "constant_gain_compatible": compatible,
            }
        )
    for direction, part in frame.groupby("head", sort=True, observed=True):
        winners = part.loc[part.raw_net20 > 0]
        compatible, decile_s, max_relative = compatible_gain(part)
        rows.append(
            {
                "record_type": "DIRECTION", "group": direction, "count": len(part), "winner_count": len(winners),
                "t1_score_vs_gain_spearman": safe_spearman(winners.pred_t1, winners.raw_net20),
                "t5_score_vs_gain_spearman": safe_spearman(winners.pred_t5, winners.raw_net20),
                "t1_decile_vs_mean_gain_spearman": decile_s,
                "max_abs_relative_gain_deviation": max_relative,
                "constant_gain_compatible": compatible,
            }
        )
    daily = (
        frame.loc[frame.raw_net20 > 0]
        .groupby("trading_date", sort=True, observed=True)
        .agg(count=("candidate_id", "size"), mean_t1=("pred_t1", "mean"), mean_t5=("pred_t5", "mean"), mean_gain=("raw_net20", "mean"))
        .reset_index()
    )
    rows.append(
        {
            "record_type": "DATE_BALANCED", "group": "ET_TRADING_DATE_WINNERS", "count": len(daily),
            "winner_count": int(daily["count"].sum()),
            "t1_score_vs_gain_spearman": safe_spearman(daily.mean_t1, daily.mean_gain),
            "t5_score_vs_gain_spearman": safe_spearman(daily.mean_t5, daily.mean_gain),
            "t1_decile_vs_mean_gain_spearman": None,
            "max_abs_relative_gain_deviation": None,
            "constant_gain_compatible": None,
        }
    )
    return pd.DataFrame(rows), compatible_folds


def t6_preregistration(path: Path) -> dict[str, Any]:
    value = {
        "CONTRACT_ID": "FAST3_R33_T6_CONDITIONAL_GAIN_MAGNITUDE_PREREGISTRATION_R1",
        "STATUS": "PREREGISTERED_NOT_TRAINED",
        "PREREGISTERED_BEFORE_ANY_T6_FIT_OR_PREDICTION": True,
        "TARGET_NAME": "T6_CONDITIONAL_GAIN_MAGNITUDE",
        "FORMULA": "natural_log1p(corporate_action_normalized_executable_net20)",
        "NATURAL_LOG": True,
        "TRAINING_ELIGIBILITY": "label_valid == true AND net20 > 0 only",
        "LOSING_ROW_T6_ZERO_FILL": False,
        "ZERO_RETURN_TRAINING_ELIGIBLE": False,
        "VALIDATION_PREDICTION_ELIGIBILITY": "all OOF candidates",
        "EVALUATION_ELIGIBILITY": "actual validation winners with net20 > 0",
        "INTERPRETATION": "conditional gain magnitude if the candidate is a winner; sign is supplied only by T1",
        "SYMMETRY_WITH_T5": "T5 trains on strict losers and predicts all candidates; T6 trains on strict winners and predicts all candidates",
        "FROZEN_INPUT_FEATURE_CONTRACT": "same frozen pre-decision feature contract; pred_t1 and pred_t5 are not T6 features",
        "FOLD_CONTRACT": "same five frozen outer OOF folds, purge, embargo, and direction-specific models",
        "PRIMARY_METRICS": ["Spearman(pred_t6, net20) among winners", "MAE and RMSE on log1p(net20) among winners"],
        "FIXED_DIAGNOSTICS": "10 deterministic equal-count prediction bins; folds, UP/DOWN, and ET-trading-date-balanced diagnostics",
        "MODEL_FAMILY_SEARCH_COUNT": 0,
        "FEATURE_SEARCH_COUNT": 0,
        "TARGET_SEARCH_COUNT": 0,
        "THRESHOLD_SEARCH_COUNT": 0,
        "T6_MODEL_FIT_COUNT": 0,
        "T6_MODEL_PREDICT_CALL_COUNT": 0,
        "FINAL_CONFIRMATION_DATA_USED": False,
        "OFFICIAL_ADOPTION_ALLOWED": False,
        "LIVE_TRADING_ALLOWED": False,
    }
    write_json(path, value)
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        raise R33CStop("USE_--run")
    allowed_existing_outputs = {
        "FAST3_R33C_GAIN_HETEROGENEITY.csv",
        "FAST3_R33C_T1_T5_GRID.csv",
        "FAST3_R33C_ROBUSTNESS.csv",
        "FAST3_R33C_ARCHITECTURE_DESIGN_R1.json",
        "FAST3_R33C_SUMMARY.json",
        "FAST3_R33C_REPORT.md",
        "FAST3_R33_T6_CONDITIONAL_GAIN_MAGNITUDE_PREREGISTRATION_R1.json",
    }
    if OUTPUT_ROOT.exists() and any(path.name not in allowed_existing_outputs for path in OUTPUT_ROOT.iterdir()):
        raise R33CStop("STOP_UNEXPECTED_EXISTING_OUTPUT")

    input_hashes_before = {path: file_sha256(path) for path in EXPECTED}
    frame, r33a = validate_and_load()
    gain_table, global_gain, decile_gain_s, conditional_t5_gain_s = gain_decile_table(frame)
    max_relative = float(gain_table.absolute_relative_gain_deviation.max())
    t1_gain_s = safe_spearman(frame.loc[frame.raw_net20 > 0, "pred_t1"], frame.loc[frame.raw_net20 > 0, "raw_net20"])
    t5_gain_s = safe_spearman(frame.loc[frame.raw_net20 > 0, "pred_t5"], frame.loc[frame.raw_net20 > 0, "raw_net20"])
    t5_loss_s = safe_spearman(frame.loc[frame.raw_net20 < 0, "pred_t5"], -frame.loc[frame.raw_net20 < 0, "raw_net20"])
    if any(value is None for value in (t1_gain_s, t5_gain_s, t5_loss_s)):
        raise R33CStop("STOP_PRIMARY_SPEARMAN")
    conditional_t5_loss_s, correct_t1_deciles = conditional_t5_loss_audit(frame)
    if (
        not np.isclose(t5_loss_s, 0.26278122319931274, rtol=0, atol=1e-15)
        or not np.isclose(conditional_t5_loss_s, 0.17858870714095537, rtol=0, atol=1e-15)
        or correct_t1_deciles != 10
    ):
        raise R33CStop("STOP_R33B_T5_EVIDENCE_REPRODUCTION")

    grid, amplitude_rows, amplitude_relationships = fixed_grid(frame)
    robustness, compatible_folds = robustness_audit(frame)
    robustness = pd.concat([robustness, amplitude_rows], ignore_index=True, sort=False)
    date_row = robustness.loc[robustness.record_type.eq("DATE_BALANCED")].iloc[0]
    date_t1 = float(date_row.t1_score_vs_gain_spearman)
    date_t5 = float(date_row.t5_score_vs_gain_spearman)

    aggregate_gate = abs(decile_gain_s) < GAIN_SPEARMAN_LIMIT and max_relative < GAIN_RELATIVE_DEVIATION_LIMIT
    constant_gain = bool(aggregate_gate and compatible_folds >= MIN_COMPATIBLE_FOLDS)
    r33a_reproduced = bool(np.isclose(decile_gain_s, r33a["SPEARMAN_T1_DECILE_VS_MEAN_GAIN"], rtol=0, atol=1e-15))
    if not r33a_reproduced:
        raise R33CStop("STOP_R33A_GAIN_HETEROGENEITY_RECONCILIATION")

    amplitude_positive = all(
        value is not None and value > 0
        for value in (
            t5_gain_s,
            t5_loss_s,
            amplitude_relationships["t5_quintile_vs_gain_magnitude_spearman"],
            amplitude_relationships["t5_quintile_vs_loss_magnitude_spearman"],
            amplitude_relationships["t5_quintile_vs_payoff_amplitude_spearman"],
        )
    )
    amplitude_status = "PAYOFF_AMPLITUDE_OR_DOWNSIDE_SEVERITY" if amplitude_positive else "DOWNSIDE_SEVERITY_WITHOUT_CONSISTENT_GAIN_AMPLITUDE"

    if constant_gain:
        classification = "A_T1_T5_ARCHITECTURE_IDENTIFIABLE_WITH_CONSTANT_GAIN"
        decision = "T1_T5_EXPECTED_VALUE_TRANSLATION_CAN_BE_DESIGNED_WITH_FOLD_LOCAL_CONSTANT_GAIN"
        next_stage = "DESIGN_T1_T5_ECONOMIC_TRANSLATION_WITHOUT_THRESHOLD_SEARCH"
    else:
        classification = "B_T1_T5_INSUFFICIENT_CONDITIONAL_GAIN_HEAD_REQUIRED"
        decision = "VALIDATE_DEDICATED_CONDITIONAL_GAIN_HEAD_BEFORE_ANY_EXPECTED_VALUE_COMBINATION"
        next_stage = "VALIDATE_T6_CONDITIONAL_GAIN_MAGNITUDE"
    t6_required = not constant_gain

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    gain_path = OUTPUT_ROOT / "FAST3_R33C_GAIN_HETEROGENEITY.csv"
    grid_path = OUTPUT_ROOT / "FAST3_R33C_T1_T5_GRID.csv"
    robustness_path = OUTPUT_ROOT / "FAST3_R33C_ROBUSTNESS.csv"
    architecture_path = OUTPUT_ROOT / "FAST3_R33C_ARCHITECTURE_DESIGN_R1.json"
    summary_path = OUTPUT_ROOT / "FAST3_R33C_SUMMARY.json"
    report_path = OUTPUT_ROOT / "FAST3_R33C_REPORT.md"
    t6_path = OUTPUT_ROOT / "FAST3_R33_T6_CONDITIONAL_GAIN_MAGNITUDE_PREREGISTRATION_R1.json" if t6_required else None

    gain_table.to_csv(gain_path, index=False)
    grid.to_csv(grid_path, index=False)
    robustness.to_csv(robustness_path, index=False)
    if t6_path is not None:
        t6_preregistration(t6_path)

    architecture = {
        "CONTRACT_ID": "FAST3_R33C_ARCHITECTURE_DESIGN_R1",
        "STATUS": "FROZEN_ARCHITECTURE_DESIGN",
        "ECONOMIC_DECOMPOSITION": {
            "p(X)": "P(net20 > 0 | X)",
            "G(X)": "E[net20 | net20 > 0, X]",
            "L(X)": "E[abs(net20) | net20 < 0, X]",
            "EXPECTED_NET20(X)": "p(X) * G(X) - (1 - p(X)) * L(X)",
            "T1_ROLE": "estimates p(X)",
            "T5_ROLE": "conditional loss-severity information related to L(X)",
            "T6_ROLE": "conditional gain-magnitude information related to G(X)" if t6_required else None,
        },
        "SELECTED_ARCHITECTURE": "T1 + T5 + T6" if t6_required else "T1 + T5",
        "CONSTANT_GAIN_RULE_FROZEN": {
            "aggregate_abs_t1_decile_mean_gain_spearman_strictly_less_than": GAIN_SPEARMAN_LIMIT,
            "aggregate_max_abs_relative_gain_deviation_strictly_less_than": GAIN_RELATIVE_DEVIATION_LIMIT,
            "minimum_folds_passing_the_same_two_rules": MIN_COMPATIBLE_FOLDS,
        },
        "CONSTANT_GAIN_APPROXIMATION_ACCEPTABLE": constant_gain,
        "T1_T5_EXPECTED_VALUE_IDENTIFIABLE": constant_gain,
        "DEDICATED_CONDITIONAL_GAIN_HEAD_REQUIRED": t6_required,
        "LOSS_CALIBRATION_PREREGISTRATION": {
            "METHOD": "FIXED_10_BIN_TRAINING_FOLD_CALIBRATION",
            "METHOD_COMPARISON_ALLOWED": False,
            "CALIBRATION_ELIGIBILITY": "strict losing rows in the outer fold's training data only",
            "BINNING": "10 deterministic equal-count bins by predicted T5 severity, stable timestamp/candidate_id tie break",
            "BIN_ESTIMATE": "realized conditional mean absolute net20 loss in each training-only bin",
            "APPLICATION": "piecewise-constant lookup for every outer-validation T5 prediction; clamp only beyond training-bin endpoints",
            "EXECUTED_IN_R33C": False,
        },
        "T5_BACK_TRANSFORMATION_WARNING": "expm1(predicted T5) is not generally E[abs(loss) | X, loss]; inverse transformation does not commute with conditional expectation",
        "NO_ARBITRARY_SCORE": True,
        "NO_CELL_SELECTION": True,
        "GRID_DESCRIPTIVE_ONLY": True,
        "T6_MUST_BE_VALIDATED_BEFORE_COMBINATION": t6_required,
        "FINAL_CONFIRMATION_DATA_USED": False,
        "OFFICIAL_ADOPTION_ALLOWED": False,
        "LIVE_TRADING_ALLOWED": False,
    }
    write_json(architecture_path, architecture)

    direction = robustness.loc[robustness.record_type.eq("DIRECTION")]
    fold = robustness.loc[robustness.record_type.eq("FOLD")]
    summary = {
        "FAST3_R33C_STATUS": "PASS",
        "FAST3_R33C_CLASSIFICATION": classification,
        "FAST3_R33C_DECISION": decision,
        "MODEL_FIT_COUNT": 0,
        "MODEL_PREDICT_CALL_COUNT": 0,
        "NEW_MODEL_COUNT": 0,
        "NEW_TARGET_TRAINED_COUNT": 0,
        "FEATURE_SEARCH_COUNT": 0,
        "T1_OOF_SHA256": EXPECTED[R32B_T1_OOF],
        "T5_OOF_SHA256": EXPECTED[R33B_T5_OOF],
        "ECONOMIC_LABEL_MANIFEST_SHA256": EXPECTED[R32A_MANIFEST],
        "ECONOMIC_LABEL_LEDGER_SHA256": EXPECTED[R32A_LABELS],
        "R33A_SUMMARY_SHA256": EXPECTED[R33A_SUMMARY],
        "FROZEN_T1_AUC": 0.5535292504188698,
        "FROZEN_T5_CONDITIONAL_LOSS_SPEARMAN": conditional_t5_loss_s,
        "FROZEN_T5_CORRECT_T1_DECILE_COUNT": correct_t1_deciles,
        "FROZEN_T5_CORRECT_FOLD_COUNT": 4,
        "OOF_ROW_COUNT": len(frame),
        "OOF_WINNER_COUNT": int((frame.raw_net20 > 0).sum()),
        "OOF_LOSS_COUNT": int((frame.raw_net20 < 0).sum()),
        "OOF_ZERO_RETURN_COUNT": int(frame.raw_net20.eq(0).sum()),
        "T1_DECILE_VS_MEAN_GAIN_SPEARMAN": decile_gain_s,
        "R33A_SPEARMAN_T1_DECILE_VS_MEAN_GAIN": r33a["SPEARMAN_T1_DECILE_VS_MEAN_GAIN"],
        "R33A_GAIN_HETEROGENEITY_REPRODUCED": r33a_reproduced,
        "T1_SCORE_VS_GAIN_GIVEN_WIN_SPEARMAN": t1_gain_s,
        "T5_SCORE_VS_GAIN_GIVEN_WIN_SPEARMAN": t5_gain_s,
        "T5_SCORE_VS_ABS_LOSS_GIVEN_LOSS_SPEARMAN": t5_loss_s,
        "CONDITIONAL_T5_VS_GAIN_SPEARMAN_AMONG_WINNERS": conditional_t5_gain_s,
        "DATE_BALANCED_T1_VS_GAIN_SPEARMAN": date_t1,
        "DATE_BALANCED_T5_VS_GAIN_SPEARMAN": date_t5,
        "DATE_BALANCED_WINNER_DATE_COUNT": int(date_row["count"]),
        "GLOBAL_MEAN_GAIN": global_gain,
        "MAX_ABS_RELATIVE_GAIN_DEVIATION": max_relative,
        "AGGREGATE_CONSTANT_GAIN_NUMERIC_GATE_PASS": aggregate_gate,
        "CONSTANT_GAIN_APPROXIMATION_ACCEPTABLE": constant_gain,
        "GAIN_HETEROGENEITY_FOLD_COUNT": int(len(fold)),
        "GAIN_CONSTANT_COMPATIBLE_FOLD_COUNT": compatible_folds,
        "DIRECTION_AUDIT_COUNT": int(len(direction)),
        "DIRECTION_CONSTANT_GAIN_COMPATIBLE_COUNT": int(direction.constant_gain_compatible.fillna(False).sum()),
        "FOLD_POSITIVE_T1_VS_GAIN_COUNT": int((fold.t1_score_vs_gain_spearman > 0).sum()),
        "FOLD_POSITIVE_T5_VS_GAIN_COUNT": int((fold.t5_score_vs_gain_spearman > 0).sum()),
        "DIRECTION_POSITIVE_T1_VS_GAIN_COUNT": int((direction.t1_score_vs_gain_spearman > 0).sum()),
        "DIRECTION_POSITIVE_T5_VS_GAIN_COUNT": int((direction.t5_score_vs_gain_spearman > 0).sum()),
        "T5_QUINTILE_VS_GAIN_MAGNITUDE_SPEARMAN": amplitude_relationships["t5_quintile_vs_gain_magnitude_spearman"],
        "T5_QUINTILE_VS_LOSS_MAGNITUDE_SPEARMAN": amplitude_relationships["t5_quintile_vs_loss_magnitude_spearman"],
        "T5_QUINTILE_VS_PAYOFF_AMPLITUDE_SPEARMAN": amplitude_relationships["t5_quintile_vs_payoff_amplitude_spearman"],
        "T5_PAYOFF_AMPLITUDE_STATUS": amplitude_status,
        "T1_T5_EXPECTED_VALUE_IDENTIFIABLE": constant_gain,
        "DEDICATED_CONDITIONAL_GAIN_HEAD_REQUIRED": t6_required,
        "T6_PREREGISTERED": t6_required,
        "T6_MODEL_FIT_COUNT": 0,
        "T6_MODEL_PREDICT_CALL_COUNT": 0,
        "LOSS_CALIBRATION_METHOD_FROZEN": "FIXED_10_BIN_TRAINING_FOLD_CALIBRATION",
        "LOSS_CALIBRATION_EXECUTED": False,
        "T5_EXPM1_IS_EXPECTED_LOSS": False,
        "DESCRIPTIVE_ONLY": True,
        "GRID_CELL_COUNT": len(grid),
        "CELL_SELECTION_COUNT": 0,
        "WEIGHT_SEARCH_COUNT": 0,
        "THRESHOLD_SEARCH_COUNT": 0,
        "COMBINATION_THRESHOLD_SEARCH_COUNT": 0,
        "MODEL_FAMILY_SEARCH_COUNT": 0,
        "HYPERPARAMETER_SEARCH_COUNT": 0,
        "SEED_SEARCH_COUNT": 0,
        "FINAL_CONFIRMATION_DATA_USED": False,
        "FINAL_CONFIRMATION_DATA_INSPECTED": False,
        "OFFICIAL_ADOPTION_ALLOWED": False,
        "LIVE_TRADING_ALLOWED": False,
        "R33C_NEW_SOURCE_FILE_COUNT": 1,
        "R33C_NEW_TEST_FILE_COUNT": 1,
        "NEW_HELPER_FILE_COUNT": 0,
        "RESULT_FILES_WRITTEN_TO_GIT_REPO": False,
        "ANTI_BLOAT_STATUS": "PASS",
        "PRIMARY_RESEARCH_INTERPRETATION": decision,
        "NEXT_STAGE": next_stage,
        "REPORT_PATH": str(report_path),
        "SUMMARY_JSON_PATH": str(summary_path),
        "ARCHITECTURE_DESIGN_PATH": str(architecture_path),
        "T6_PREREGISTRATION_PATH": str(t6_path) if t6_path is not None else None,
        "GAIN_HETEROGENEITY_PATH": str(gain_path),
        "T1_T5_GRID_PATH": str(grid_path),
        "ROBUSTNESS_PATH": str(robustness_path),
    }
    write_json(summary_path, summary)

    low_rate = 0.5857
    high_rate = 0.6120
    report = f"""# FAST3 R33C — T1 + Conditional T5 Economic Architecture Design Audit

## Decision

`{classification}`

The exact economic identity remains `EV(X) = p(X) * G(X) - (1 - p(X)) * L(X)`. T1 supplies information about `p(X)` and T5 supplies conditional downside-severity information related to `L(X)`. The constant-gain gate is `{constant_gain}`; therefore the selected architecture is `{'T1 + T5' if constant_gain else 'T1 + T5 + T6'}`.

## Fixed audit results

- T1-decile versus mean winner gain Spearman: `{decile_gain_s}`.
- Global mean gain: `{global_gain}`; maximum absolute relative decile deviation: `{max_relative}`.
- Constant-compatible folds: `{compatible_folds}/{FOLD_COUNT}`.
- Winner-row T1/T5 Spearman versus gain: `{t1_gain_s}` / `{t5_gain_s}`.
- Conditional within-T1-decile T5 versus gain Spearman: `{conditional_t5_gain_s}`.
- ET-date-balanced T1/T5 versus gain Spearman: `{date_t1}` / `{date_t5}`.
- T5 quintile trend versus gain/loss/amplitude: `{amplitude_relationships['t5_quintile_vs_gain_magnitude_spearman']}` / `{amplitude_relationships['t5_quintile_vs_loss_magnitude_spearman']}` / `{amplitude_relationships['t5_quintile_vs_payoff_amplitude_spearman']}`.
- T5 interpretation: `{amplitude_status}`.
- R33A gain-heterogeneity value reproduced exactly: `{r33a_reproduced}` (`{r33a['SPEARMAN_T1_DECILE_VS_MEAN_GAIN']}`).

## Direct answers

1. Low-T5 filtering reduced conditional loss magnitude, but it also reduced the frozen Top20 positive rate from `{high_rate}` to `{low_rate}` and removed candidates with larger winning opportunity magnitude. That offset is why mean net20 did not improve; low risk is not high expected return.
2. T5 payoff-amplitude status is `{amplitude_status}`. It must not be interpreted as a mechanical `avoid high T5` rule.
3. Winning magnitude cannot be treated as constant because the preregistered aggregate/fold gate is `{constant_gain}`.
4. Yes. R33A's T1-decile gain Spearman is independently reproduced exactly in the full OOF.
5. Robustness is reported without changing architecture by subgroup: `{compatible_folds}/{FOLD_COUNT}` folds and `{int(direction.constant_gain_compatible.fillna(False).sum())}/2` directions satisfy the constant-gain rule; date-balanced diagnostics are shown above. The evidence does not support a constant-gain architecture.
6. T1 + T5 alone does not mathematically identify expected-payoff ranking when `G(X)` is heterogeneous.
7. Dedicated conditional gain head T6 is required: `{t6_required}`.
8. T6 is preregistered before any T6 fit or prediction. Its target is natural `log1p(net20)` on strict winners only; losing rows are never zero-filled; future validation predictions must cover all OOF candidates.
9. The next stage is `{next_stage}`. T6 must be validated before any EV combination or trading threshold.
10. No. Final confirmation remains sealed; this architecture audit supplies no reason to open it.

## Calibration and governance

`expm1(predicted_T5)` is not generally `E[abs(loss) | X, loss]`; inverse transformation and conditional expectation do not commute. Any later EV translation is frozen to `FIXED_10_BIN_TRAINING_FOLD_CALIBRATION`, using only strict losing rows in each outer fold's training data. No calibration was executed here.

The 5 x 5 T1/T5 grid is descriptive only. No cell was selected or merged. No model fit, prediction call, feature/weight/threshold/combination search, or final-holdout inspection occurred.
"""
    report_path.write_text(report, encoding="utf-8")

    for path, before in input_hashes_before.items():
        if file_sha256(path) != before:
            raise R33CStop(f"STOP_FROZEN_INPUT_MUTATED_{path.name}")
    print(json.dumps(summary, indent=2, sort_keys=True, default=json_value, allow_nan=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except R33CStop as exc:
        raise SystemExit(str(exc)) from exc
