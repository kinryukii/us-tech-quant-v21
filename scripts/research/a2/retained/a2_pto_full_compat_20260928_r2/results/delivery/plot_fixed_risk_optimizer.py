"""Plot completed fixed cells; never fit, select, or rewrite source results."""
import csv
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path
from statistics import fmean

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
os.environ["MPLCONFIGDIR"] = str(OUT / "mpl_cache")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import numpy as np

SOURCE = ROOT / "results/analysis/ALL_COMBINATIONS.csv"
risks, opts = [], []
with (ROOT / "RISK_OPTIMIZER_COMPATIBILITY.csv").open(encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        if r["risk"] not in risks:
            risks.append(r["risk"])
        if r["optimizer"] not in opts:
            opts.append(r["optimizer"])
assert len(risks) == 13 and len(opts) == 4
cells = defaultdict(list)
controls = defaultdict(dict)
with SOURCE.open(encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        if r["layer"] != "pto" or r["replay_complete"] != "True":
            continue
        key = (int(r["year"]), r["risk"], r["optimizer"])
        cells[key].append((float(r["indicative_return"]), float(r["mean_gross_exposure"])))
        if r["optimizer"] == "positive_equal":
            values = tuple(float(r[k]) for k in (
                "indicative_return", "indicative_max_drawdown", "mean_gross_exposure", "total_fees"))
            controls[(int(r["year"]), r["group"], r["fusion"])][r["risk"]] = values
assert len(cells) == 104 and all(len(v) == 129 for v in cells.values())
assert all(len(v) == 13 and len(set(v.values())) == 1 for v in controls.values())
assert len(controls) == 258
values = {k: (fmean(r[0] for r in v), fmean(r[1] for r in v)) for k, v in cells.items()}
max_return = max(abs(v[0]) for v in values.values())
font_path = Path("C:/Windows/Fonts/msyh.ttc")
font = FontProperties(fname=str(font_path)) if font_path.exists() else None
plt.rcParams["axes.unicode_minus"] = False
fig, axes = plt.subplots(2, 2, figsize=(13, 11), layout="constrained")
labels = {
    "positive_equal": "Positive equal", "mean_variance": "Mean variance",
    "robust_mv": "Robust MV", "cvar": "CVaR",
    "factor_analysis": "FA", "lw_learned_scale_average": "LW + learned scale avg",
    "lw_hgb_scale": "LW + HGB scale", "lw_mlp_scale": "LW + MLP scale",
    "lw_oas_average": "LW / OAS avg", "pca_fa_average": "PCA / FA avg",
}
for yi, year in enumerate((2025, 2026)):
    for metric in (0, 1):
        ax = axes[yi, metric]
        a = np.array([[values[(year, risk, opt)][metric] for opt in opts] for risk in risks])
        im = ax.imshow(a, aspect="auto", cmap="RdBu_r" if metric == 0 else "Blues",
                       vmin=-max_return if metric == 0 else 0,
                       vmax=max_return if metric == 0 else 0.95)
        ax.set_xticks(range(4), [labels.get(o, o) for o in opts], fontsize=9)
        ax.set_yticks(range(13), [labels.get(r, r) for r in risks], fontsize=9)
        for y in range(13):
            for x in range(4):
                normalized = abs(a[y, x]) / max_return if metric == 0 else a[y, x] / .95
                ax.text(x, y, f"{a[y, x] * 100:.1f}%", ha="center", va="center", fontsize=8,
                        color="white" if normalized > .65 else "black")
        ax.set_title(f"{year} " + ("净收益均值" if metric == 0 else "平均股票敞口"),
                     fontproperties=font, fontsize=13)
        fig.colorbar(im, ax=ax, shrink=.65, format=lambda x, _: f"{x*100:.0f}%")
fig.suptitle("固定风险 × 优化比较：每格 129 个已完成独立账户，等权描述性均值", fontproperties=font, fontsize=15)
fig.supxlabel("账户均值不是目标仓位融合；2026 截至 9/24。合格子池、既往曝光、价格指数研究结果；不代表真实股东总回报。",
              fontproperties=font, fontsize=9)
fig.savefig(OUT / "risk_optimizer_comparison.png", dpi=160)
fig.savefig(OUT / "risk_optimizer_comparison.svg")
plt.close(fig)
receipt = {
    "status": "DERIVED_FIXED_RESULTS_VISUALIZATION",
    "source": str(SOURCE), "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    "source_results_unchanged": True, "new_fits": 0, "new_searches": 0,
    "cells": 104, "independent_accounts_per_cell": 129,
    "positive_equal_risk_invariance": {"forecast_years": 258, "risks_each": 13, "exact_metrics": 4, "status": "PASS"},
    "aggregation": "Arithmetic mean of completed independent PTO accounts, descriptive and dependent; not a fused-account strategy",
    "limits": ["formal 2026 FULLPOOL BLOCKED_DATA", "prior 2026 exposure", "price-index results not certified shareholder total return", "feasible approximate solves included as flagged in source CSV"],
    "values": [{"year": y, "risk": r, "optimizer": o, "return_mean": v[0], "exposure_mean": v[1]}
               for (y, r, o), v in values.items()],
    "outputs_sha256": {name: hashlib.sha256((OUT / name).read_bytes()).hexdigest()
                       for name in ("risk_optimizer_comparison.png", "risk_optimizer_comparison.svg")},
}
(OUT / "VISUALIZATION_RECEIPT.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"status": receipt["status"], "cells": 104, "positive_equal_control": "PASS"}))
