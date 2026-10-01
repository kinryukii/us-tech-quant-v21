"""Research figure: executed cash ratios and frozen ensemble weights, never NAV."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, PercentFormatter
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
BASE = ROOT / "ensemble_2026/cost_10"
PATHS = {
    "ensemble_equal": ("Equal blend", "#2563eb"),
    "ensemble_consensus_risk": ("Consensus + risk", "#0f827c"),
    "ensemble_stacked": ("Learned blend", "#8b46c4"),
}
LABELS = {"joint_ridge": "Ridge", "joint_elastic_net": "Elastic Net",
          "joint_logistic": "Logistic", "joint_hgb": "HGB",
          "joint_quantile_risk": "Quantile risk", "joint_mlp": "Small MLP"}


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    source_hashes, datasets, summaries = {}, {}, {}
    for name in PATHS:
        receipt_path = BASE / name / "PATH_COMPLETE.json"
        daily_path = BASE / name / "daily.parquet"
        if not receipt_path.exists():
            raise RuntimeError(f"WAIT_FOR_COMPLETED_PATH: {name}")
        receipt = read(receipt_path)
        assert receipt["audit"]["status"] == "PASS"
        assert receipt["metrics"]["policy"] == name and receipt["metrics"]["year"] == 2026
        assert receipt["metrics"]["cost_bps"] == 10
        assert sha(daily_path) == receipt["ledger_sha256"]["daily"]
        # Do not load any numerical return/NAV column. cash_weight is an existing
        # post-execution ledger field; uncertified denominators are masked below.
        daily = pd.read_parquet(daily_path, columns=["date", "cash", "cash_weight", "valuation_status"])
        daily = daily.sort_values("date").reset_index(drop=True)
        assert daily.date.dt.year.eq(2026).all() and not daily.date.duplicated().any()
        valid = daily.valuation_status.eq("certified") & np.isfinite(daily.cash_weight)
        assert daily.loc[valid, "cash_weight"].between(-1e-8, 1 + 1e-8).all()
        assert np.isfinite(daily.cash).all() and daily.cash.ge(-1e-6).all()
        datasets[name] = (daily.date, daily.cash, daily.cash_weight.where(valid))
        summaries[name] = {"total_days": len(daily), "plotted_certified_days": int(valid.sum()),
                           "omitted_uncertified_or_nonfinite_days": int((~valid).sum()),
                           "first_date": str(daily.date.min().date()),
                           "last_date": str(daily.date.max().date())}
        source_hashes.update({str(p): sha(p) for p in [receipt_path, daily_path]})

    meta_path = ROOT / "ensemble_artifacts/TRAIN_RECEIPT.json"
    weights_path = ROOT / "ensemble_artifacts/final_weights.json"
    receipt, weights_artifact = read(meta_path), read(weights_path)
    fitted = next(x for x in receipt["fits"] if x["stage"] == "final")
    assert sha(weights_path) == fitted["artifact_sha256"]
    assert weights_artifact["training_cutoff_exclusive"] == "2026-01-01"
    members = weights_artifact["methods"]
    weights = np.asarray([weights_artifact["weights"][name] for name in members])
    assert len(weights) == 6 and np.isfinite(weights).all() and abs(weights.sum() - 1) < 1e-8
    source_hashes.update({str(p): sha(p) for p in [meta_path, weights_path]})

    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 11,
                         "axes.edgecolor": "#cbd5e1", "axes.labelcolor": "#475569",
                         "xtick.color": "#64748b", "ytick.color": "#64748b",
                         "text.color": "#172439", "axes.spines.top": False,
                         "axes.spines.right": False, "savefig.facecolor": "#f7f9fc"}):
        fig = plt.figure(figsize=(15.5, 10), facecolor="#f7f9fc")
        grid = fig.add_gridspec(2, 2, left=.075, right=.965, top=.775, bottom=.22,
                               width_ratios=[2.05, 1], wspace=.27, hspace=.65)
        ax = fig.add_subplot(grid[0, 0], facecolor="white")
        cx = fig.add_subplot(grid[1, 0], facecolor="white", sharex=ax)
        bx = fig.add_subplot(grid[:, 1], facecolor="white")
        fig.text(.075, .943, "2026 verified-subpool diagnostic", fontsize=22, fontweight="bold")
        fig.text(.075, .9, "Prior test exposure  |  Executed cash balances, cash shares and frozen collaboration weights",
                 fontsize=13, color="#475569")
        fig.text(.075, .851, "10 bps per side  ·  Same account constraints  ·  No 2026 weight fitting",
                 fontsize=11, color="#64748b")

        for name, (label, color) in PATHS.items():
            dates, cash, cash_ratio = datasets[name]
            ax.plot(dates, cash, label=label, color=color, lw=1.9, alpha=.92)
            cx.plot(dates, cash_ratio, label=label, color=color, lw=1.9, alpha=.92)
        ax.set_title("Actual cash balance  |  full ledger", loc="left", pad=16, fontsize=14, fontweight="bold")
        ax.set_ylim(bottom=0)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"${value / 1e6:.1f}m"))
        ax.set_ylabel("Cash dollars")
        cx.set_title("Cash share  |  certified valuation dates only", loc="left", pad=16, fontsize=14, fontweight="bold")
        cx.set_ylim(0, 1.02)
        cx.yaxis.set_major_formatter(PercentFormatter(1))
        cx.set_ylabel("Cash / certified account value")
        for axis in [ax, cx]:
            axis.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
            axis.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
            axis.grid(axis="y", color="#e2e8f0", lw=.7)
            axis.margins(x=.01)
        handles, labels = ax.get_legend_handles_labels()
        fig.legend(handles, labels, loc="lower left", bbox_to_anchor=(.07, .14), ncol=3,
                   frameon=False, columnspacing=2.4, handlelength=2.5, fontsize=11)

        y = np.arange(len(weights))
        colors = ["#a9b4c5"] * len(weights)
        for i, name in enumerate(members):
            if name == "joint_quantile_risk":
                colors[i] = "#0f827c"
            elif name == "joint_mlp":
                colors[i] = "#8b46c4"
        bx.barh(y, weights, color=colors, height=.55)
        bx.set_yticks(y, [LABELS[name] for name in members])
        bx.invert_yaxis()
        bx.set_xlim(0, .41)
        bx.set_xticks([0, .1, .2, .3, .4])
        bx.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        bx.grid(axis="x", color="#e2e8f0", lw=.7)
        bx.set_axisbelow(True)
        bx.set_title("Learned blend: final weights", loc="left", pad=18, fontsize=14, fontweight="bold")
        bx.set_xlabel("Share of model contribution")
        for i, weight in enumerate(weights):
            bx.text(weight + .01, i, f"{weight:.2%}", va="center", fontsize=11, color="#172439")

        missing = sum(x["omitted_uncertified_or_nonfinite_days"] for x in summaries.values())
        fig.text(.075, .113, "Cash balances are ledger dollars. Cash shares need certified account values; gaps are left unfilled."
                 + f"  ({missing} omitted path-days)", fontsize=10, color="#475569")
        fig.text(.075, .078, "Weights learned from 2025 out-of-sample base returns; combining targets changes realized costs and execution.",
                 fontsize=10, color="#64748b")
        fig.text(.075, .043, "Retrospectively verified subset; GLW event-date conflict remains unresolved. No performance or full-pool certification implied.",
                 fontsize=9.5, color="#64748b")
        fig.savefig(ROOT / "ENSEMBLE_OVERVIEW.png", dpi=220)
        fig.savefig(ROOT / "ENSEMBLE_OVERVIEW.svg")
        plt.close(fig)

    assert all(sha(path) == expected for path, expected in source_hashes.items())
    proof = {"status": "PASS", "created_utc": datetime.now(timezone.utc).isoformat(),
             "plotted_columns": ["date", "cash", "cash_weight", "valuation_status", "final_meta_weights"],
             "numerical_nav_or_return_columns_read": False,
             "uncertified_cash_ratios_masked": True, "filled_missing_values": False,
             "source_sha256": source_hashes, "source_files_unchanged": True,
             "paths": summaries, "outputs_sha256": {name: sha(ROOT / name) for name in
                                                        ["ENSEMBLE_OVERVIEW.png", "ENSEMBLE_OVERVIEW.svg"]}}
    (ROOT / "audit/ENSEMBLE_PLOT_RECEIPT.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "PASS", "paths": summaries, "outputs": ["ENSEMBLE_OVERVIEW.png", "ENSEMBLE_OVERVIEW.svg"]}), flush=True)


if __name__ == "__main__":
    main()
