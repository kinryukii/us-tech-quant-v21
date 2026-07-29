from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

VERSION = "V22.054_FAST3_TERMINATION_AND_ATTRIBUTION_AUDIT_R1"
MIN_PIT_COUNT = 20


class AuditError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.integer, np.floating)):
        if isinstance(value, np.floating) and not np.isfinite(value):
            return None
        return value.item()
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=json_default) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def validate_summary(summary: Mapping[str, Any], version: str) -> None:
    if version == "052":
        expected = {
            "final_status": "PASS",
            "final_decision": "NO_LONG_NONOVERLAP_CANDIDATE_QUALIFIED",
            "data_ready_for_v22_053": False,
        }
    elif version == "053":
        expected = {
            "final_status": "PASS",
            "final_decision": "NO_PULLBACK_REENTRY_CANDIDATE_QUALIFIED",
            "data_ready_for_v22_054": False,
        }
    else:
        raise AuditError(f"Unsupported version: {version}")

    expected.update(
        {
            "entry_filter_optimization_executed": False,
            "exit_optimization_executed": False,
            "broker_action_allowed": False,
            "paper_trading_allowed": False,
            "official_adoption_allowed": False,
        }
    )
    failed = [
        f"{key}: expected {wanted!r}, got {summary.get(key)!r}"
        for key, wanted in expected.items()
        if summary.get(key) != wanted
    ]
    if failed:
        raise AuditError(f"V22.{version} validation failed: " + "; ".join(failed))


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise AuditError(f"Missing JSON: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_csv(path: Path, label: str) -> pd.DataFrame:
    if not path.exists():
        raise AuditError(f"Missing CSV: {path}")
    frame = pd.read_csv(path)
    if frame.empty:
        raise AuditError(f"{label} is empty: {path}")
    return frame


def normalize_trades(frame: pd.DataFrame, architecture: str) -> pd.DataFrame:
    required = {
        "execution_symbol",
        "horizon_minutes",
        "trade_date",
        "calendar_year",
        "net_return",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise AuditError(f"{architecture} trades missing columns: {missing}")

    result = frame.copy()
    result["architecture"] = architecture
    result["execution_symbol"] = result["execution_symbol"].astype(str)
    result["horizon_minutes"] = pd.to_numeric(result["horizon_minutes"], errors="raise").astype(int)
    result["calendar_year"] = pd.to_numeric(result["calendar_year"], errors="raise").astype(int)
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="raise").dt.strftime("%Y-%m-%d")
    result["net_return"] = pd.to_numeric(result["net_return"], errors="coerce")

    if "signal_excess_pit_net" in result.columns:
        result["signal_excess_pit_net"] = pd.to_numeric(
            result["signal_excess_pit_net"], errors="coerce"
        )
    else:
        result["signal_excess_pit_net"] = np.nan

    if "pit_baseline_eligible" in result.columns:
        values = result["pit_baseline_eligible"]
        if values.dtype == bool:
            eligible = values
        else:
            eligible = values.astype(str).str.lower().isin({"true", "1", "yes"})
    elif "matched_pit_count" in result.columns:
        eligible = pd.to_numeric(result["matched_pit_count"], errors="coerce") >= MIN_PIT_COUNT
    else:
        eligible = result["signal_excess_pit_net"].notna()

    result["pit_eligible_corrected"] = eligible & result["signal_excess_pit_net"].notna()
    return result.dropna(subset=["net_return"]).reset_index(drop=True)


def corrected_annual_summary(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    keys = ["architecture", "execution_symbol", "horizon_minutes", "calendar_year"]
    for group_key, group in trades.groupby(keys, sort=True):
        architecture, symbol, horizon, year = group_key
        pit = group.loc[group["pit_eligible_corrected"]]
        rows.append(
            {
                "architecture": architecture,
                "execution_symbol": symbol,
                "horizon_minutes": int(horizon),
                "calendar_year": int(year),
                "trade_count": int(len(group)),
                "trade_day_count": int(group["trade_date"].nunique()),
                "mean_net_return": float(group["net_return"].mean()),
                "median_net_return": float(group["net_return"].median()),
                "positive_rate": float((group["net_return"] > 0).mean()),
                "pit_eligible_trade_count_corrected": int(len(pit)),
                "mean_excess_pit": float(pit["signal_excess_pit_net"].mean()) if len(pit) else np.nan,
                "median_excess_pit": float(pit["signal_excess_pit_net"].median()) if len(pit) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def daily_compound(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    keys = ["architecture", "execution_symbol", "horizon_minutes", "trade_date"]
    for group_key, group in trades.groupby(keys, sort=True):
        architecture, symbol, horizon, trade_date = group_key
        pit = group.loc[group["pit_eligible_corrected"]]
        net = group["net_return"].to_numpy(dtype=float)
        excess = pit["signal_excess_pit_net"].to_numpy(dtype=float)
        rows.append(
            {
                "architecture": architecture,
                "execution_symbol": symbol,
                "horizon_minutes": int(horizon),
                "trade_date": str(trade_date),
                "calendar_year": int(str(trade_date)[:4]),
                "trade_count": int(len(group)),
                "pit_eligible_trade_count": int(len(pit)),
                "daily_compound_net_return": float(np.prod(1 + net) - 1),
                "daily_compound_excess_pit": float(np.prod(1 + excess) - 1) if len(excess) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def nav_and_mdd(returns: pd.Series) -> tuple[float, float]:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if clean.empty:
        return np.nan, np.nan
    nav = (1 + clean).cumprod()
    dd = nav / nav.cummax() - 1
    return float(nav.iloc[-1] - 1), float(dd.min())


def concentration(values: pd.Series) -> dict[str, float]:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    positive = clean[clean > 0].sort_values(ascending=False)
    negative = clean[clean < 0].sort_values()
    top_count = max(1, math.ceil(len(clean) * 0.05)) if len(clean) else 0
    return {
        "top_5pct_positive_contribution_share": (
            float(positive.head(top_count).sum() / positive.sum()) if len(positive) else np.nan
        ),
        "top_10_days_positive_contribution_share": (
            float(positive.head(min(10, len(positive))).sum() / positive.sum())
            if len(positive)
            else np.nan
        ),
        "worst_10_days_negative_contribution_share": (
            float(abs(negative.head(min(10, len(negative))).sum()) / abs(negative.sum()))
            if len(negative)
            else np.nan
        ),
    }


def attribution(daily: pd.DataFrame, annual: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    keys = ["architecture", "execution_symbol", "horizon_minutes"]
    for group_key, group in daily.groupby(keys, sort=True):
        architecture, symbol, horizon = group_key
        ordered = group.sort_values("trade_date")
        total, mdd = nav_and_mdd(ordered["daily_compound_net_return"])
        annual_group = annual.loc[
            (annual["architecture"] == architecture)
            & (annual["execution_symbol"] == symbol)
            & (annual["horizon_minutes"] == int(horizon))
        ]
        best = annual_group.sort_values("mean_net_return", ascending=False).iloc[0]
        worst = annual_group.sort_values("mean_net_return").iloc[0]
        rows.append(
            {
                "architecture": architecture,
                "execution_symbol": symbol,
                "horizon_minutes": int(horizon),
                "trade_day_count": int(len(ordered)),
                "daily_mean_net_return": float(ordered["daily_compound_net_return"].mean()),
                "daily_median_net_return": float(ordered["daily_compound_net_return"].median()),
                "daily_positive_rate": float((ordered["daily_compound_net_return"] > 0).mean()),
                "cumulative_compound_return": total,
                "max_drawdown": mdd,
                "best_year": int(best["calendar_year"]),
                "best_year_mean_net_return": float(best["mean_net_return"]),
                "worst_year": int(worst["calendar_year"]),
                "worst_year_mean_net_return": float(worst["mean_net_return"]),
                "positive_year_count": int((annual_group["mean_net_return"] > 0).sum()),
                "negative_year_count": int((annual_group["mean_net_return"] < 0).sum()),
                **concentration(ordered["daily_compound_net_return"]),
            }
        )
    return pd.DataFrame(rows)


def leave_one_year_out(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    keys = ["architecture", "execution_symbol", "horizon_minutes"]
    for group_key, group in trades.groupby(keys, sort=True):
        architecture, symbol, horizon = group_key
        for omitted in sorted(group["calendar_year"].unique()):
            remain = group.loc[group["calendar_year"] != omitted]
            pit = remain.loc[remain["pit_eligible_corrected"]]
            rows.append(
                {
                    "architecture": architecture,
                    "execution_symbol": symbol,
                    "horizon_minutes": int(horizon),
                    "omitted_year": int(omitted),
                    "remaining_trade_count": int(len(remain)),
                    "mean_net_return": float(remain["net_return"].mean()),
                    "median_net_return": float(remain["net_return"].median()),
                    "positive_rate": float((remain["net_return"] > 0).mean()),
                    "pit_eligible_trade_count": int(len(pit)),
                    "mean_excess_pit": float(pit["signal_excess_pit_net"].mean()) if len(pit) else np.nan,
                    "net_sign_positive": bool(remain["net_return"].mean() > 0),
                    "excess_sign_positive": bool(len(pit) and pit["signal_excess_pit_net"].mean() > 0),
                }
            )
    return pd.DataFrame(rows)


def loo_summary(loo: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    keys = ["architecture", "execution_symbol", "horizon_minutes"]
    for group_key, group in loo.groupby(keys, sort=True):
        architecture, symbol, horizon = group_key
        rows.append(
            {
                "architecture": architecture,
                "execution_symbol": symbol,
                "horizon_minutes": int(horizon),
                "omission_count": int(len(group)),
                "all_loo_mean_net_positive": bool(group["net_sign_positive"].all()),
                "all_loo_mean_excess_positive": bool(group["excess_sign_positive"].all()),
                "minimum_loo_mean_net_return": float(group["mean_net_return"].min()),
                "maximum_loo_mean_net_return": float(group["mean_net_return"].max()),
                "minimum_loo_mean_excess_pit": float(group["mean_excess_pit"].min()),
                "maximum_loo_mean_excess_pit": float(group["mean_excess_pit"].max()),
                "loo_net_sign_flip": bool(group["net_sign_positive"].nunique() > 1),
                "loo_excess_sign_flip": bool(group["excess_sign_positive"].nunique() > 1),
            }
        )
    return pd.DataFrame(rows)


def worst_days(daily: pd.DataFrame, count: int = 10) -> pd.DataFrame:
    parts = []
    keys = ["architecture", "execution_symbol", "horizon_minutes"]
    for _, group in daily.groupby(keys, sort=True):
        parts.append(group.nsmallest(count, "daily_compound_net_return"))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def run_audit(v22_052_root: Path, v22_053_root: Path, result_dir: Path) -> dict[str, Any]:
    s52_path = v22_052_root / "v22_052_summary.json"
    s53_path = v22_053_root / "v22_053_summary.json"
    s52 = read_json(s52_path)
    s53 = read_json(s53_path)
    validate_summary(s52, "052")
    validate_summary(s53, "053")

    t52 = normalize_trades(
        read_csv(v22_052_root / "v22_052_trades.csv", "V22.052 trades"),
        "V22.052_MOMENTUM_STATE_TRANSITION",
    )
    t53 = normalize_trades(
        read_csv(v22_053_root / "v22_053_trades.csv", "V22.053 trades"),
        "V22.053_PULLBACK_REENTRY",
    )
    trades = pd.concat([t52, t53], ignore_index=True, sort=False)

    annual = corrected_annual_summary(trades)
    daily = daily_compound(trades)
    attr = attribution(daily, annual)
    loo = leave_one_year_out(trades)
    loo_s = loo_summary(loo)
    worst = worst_days(daily)

    merged = attr.merge(
        loo_s,
        on=["architecture", "execution_symbol", "horizon_minutes"],
        how="left",
    )
    merged["year_instability"] = (
        (merged["positive_year_count"] > 0) & (merged["negative_year_count"] > 0)
    )

    result_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "annual": result_dir / "v22_054_corrected_annual_pit_summary.csv",
        "daily": result_dir / "v22_054_daily_compound_returns.csv",
        "attribution": result_dir / "v22_054_architecture_attribution.csv",
        "loo": result_dir / "v22_054_leave_one_year_out.csv",
        "loo_summary": result_dir / "v22_054_loo_stability_summary.csv",
        "worst": result_dir / "v22_054_worst_10_trade_days.csv",
        "summary": result_dir / "v22_054_summary.json",
        "manifest": result_dir / "v22_054_run_manifest.json",
    }
    annual.to_csv(outputs["annual"], index=False, encoding="utf-8-sig")
    daily.to_csv(outputs["daily"], index=False, encoding="utf-8-sig")
    attr.to_csv(outputs["attribution"], index=False, encoding="utf-8-sig")
    loo.to_csv(outputs["loo"], index=False, encoding="utf-8-sig")
    loo_s.to_csv(outputs["loo_summary"], index=False, encoding="utf-8-sig")
    worst.to_csv(outputs["worst"], index=False, encoding="utf-8-sig")

    summary = {
        "version": VERSION,
        "final_status": "PASS",
        "final_decision": "FAST3_SIGNAL_FAMILY_TERMINATED_NOT_ROBUST",
        "v22_052_validated": True,
        "v22_053_validated": True,
        "minute_data_scanned": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "open_d_called": False,
        "history_download_executed": False,
        "v22_052_summary_sha256": sha256_file(s52_path),
        "v22_053_summary_sha256": sha256_file(s53_path),
        "v22_052_trade_count": int(len(t52)),
        "v22_053_trade_count": int(len(t53)),
        "combined_trade_count": int(len(trades)),
        "corrected_pit_eligible_trade_count": int(trades["pit_eligible_corrected"].sum()),
        "architecture_count_audited": int(trades["architecture"].nunique()),
        "candidate_schedule_count_audited": int(len(merged)),
        "year_instability_schedule_count": int(merged["year_instability"].sum()),
        "loo_net_sign_flip_schedule_count": int(merged["loo_net_sign_flip"].fillna(False).sum()),
        "loo_excess_sign_flip_schedule_count": int(merged["loo_excess_sign_flip"].fillna(False).sum()),
        "new_strategy_candidate_created": False,
        "fast3_signal_family_robust": False,
        "fast3_development_continue": False,
        "entry_filter_optimization_allowed": False,
        "exit_optimization_allowed": False,
        "paper_trading_allowed": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "next_research_line": "V22.055_ABCDE_FORWARD_PORTFOLIO_VALIDATION_R1",
    }
    atomic_json(outputs["summary"], summary)
    atomic_json(
        outputs["manifest"],
        {
            "version": VERSION,
            "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "inputs": {"v22_052_root": str(v22_052_root), "v22_053_root": str(v22_053_root)},
            "outputs": {key: str(value) for key, value in outputs.items()},
            "read_only_guards": {
                "minute_data_scanned": False,
                "canonical_files_modified": False,
                "raw_files_modified": False,
                "open_d_called": False,
                "history_download_executed": False,
            },
        },
    )
    return {"summary": summary, "outputs": outputs, "result_dir": result_dir}


def print_final(result: Mapping[str, Any]) -> None:
    s = result["summary"]
    print(f"FINAL_STATUS={s['final_status']}")
    print(f"FINAL_DECISION={s['final_decision']}")
    print("FILES_MODIFIED=None")
    print("V22_052_VALIDATED=True")
    print("V22_053_VALIDATED=True")
    print("MINUTE_DATA_SCANNED=False")
    print("CANONICAL_FILES_MODIFIED=False")
    print("RAW_FILES_MODIFIED=False")
    print("OPEN_D_CALLED=False")
    print("HISTORY_DOWNLOAD_EXECUTED=False")
    print(f"V22_052_TRADE_COUNT={s['v22_052_trade_count']}")
    print(f"V22_053_TRADE_COUNT={s['v22_053_trade_count']}")
    print(f"COMBINED_TRADE_COUNT={s['combined_trade_count']}")
    print(f"CORRECTED_PIT_ELIGIBLE_TRADE_COUNT={s['corrected_pit_eligible_trade_count']}")
    print(f"YEAR_INSTABILITY_SCHEDULE_COUNT={s['year_instability_schedule_count']}")
    print(f"LOO_NET_SIGN_FLIP_SCHEDULE_COUNT={s['loo_net_sign_flip_schedule_count']}")
    print(f"LOO_EXCESS_SIGN_FLIP_SCHEDULE_COUNT={s['loo_excess_sign_flip_schedule_count']}")
    print("NEW_STRATEGY_CANDIDATE_CREATED=False")
    print("FAST3_SIGNAL_FAMILY_ROBUST=False")
    print("FAST3_DEVELOPMENT_CONTINUE=False")
    print("ENTRY_FILTER_OPTIMIZATION_ALLOWED=False")
    print("EXIT_OPTIMIZATION_ALLOWED=False")
    print("PAPER_TRADING_ALLOWED=False")
    print("BROKER_ACTION_ALLOWED=False")
    print("OFFICIAL_ADOPTION_ALLOWED=False")
    print("NEXT_RESEARCH_LINE=V22.055_ABCDE_FORWARD_PORTFOLIO_VALIDATION_R1")
    print(f"SUMMARY_PATH={result['outputs']['summary']}")
    print(f"RESULT_DIRECTORY={result['result_dir']}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--v22-052-root",
        default=r"D:\us-tech-quant-results\v22\V22.052_FAST3_LONG_NONOVERLAP_STATE_TRANSITION_STUDY_R1",
    )
    parser.add_argument(
        "--v22-053-root",
        default=r"D:\us-tech-quant-results\v22\V22.053_FAST3_TREND_PULLBACK_VWAP_REENTRY_STUDY_R1",
    )
    parser.add_argument(
        "--result-dir",
        default=r"D:\us-tech-quant-results\v22\V22.054_FAST3_TERMINATION_AND_ATTRIBUTION_AUDIT_R1",
    )
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.execute:
        print("FINAL_STATUS=BLOCKED_EXECUTE_FLAG_REQUIRED")
        return 2
    try:
        result = run_audit(Path(args.v22_052_root), Path(args.v22_053_root), Path(args.result_dir))
        print_final(result)
        return 0
    except Exception as exc:
        print("FINAL_STATUS=FAIL")
        print(f"ERROR_TYPE={type(exc).__name__}")
        print(f"ERROR={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
