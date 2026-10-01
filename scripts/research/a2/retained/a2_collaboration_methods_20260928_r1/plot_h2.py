"""Read-only, prespecified-order scientific comparison plot from the saved table."""
from pathlib import Path
import hashlib
import sys
sys.dont_write_bytecode = True

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager, ticker
from matplotlib.patches import Patch
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
CSV = ROOT / "ALL_COMPARISONS.csv"
OUTPUT = ROOT / "H2_COMPARISON.png"

# This order is fixed by method design; no metric is used to rank or select rows.
ROWS = [
    ("fixed_pred", "固定预测融合", "组合设计"),
    ("learned_fixed", "学习固定权重", "组合设计"),
    ("stack_ridge", "线性 Stacking", "组合设计"),
    ("stack_mlp", "小型 MLP Stacking", "组合设计"),
    ("conditional_gate", "条件门控", "组合设计"),
    ("ridge_then_hgb", "Ridge → HGB 修正", "组合设计"),
    ("hgb_then_ridge", "HGB → Ridge 修正", "组合设计"),
    ("decision_blend", "目标仓位融合", "组合设计"),
    ("base_ridge", "同基础控制：Ridge", "同基础控制"),
    ("base_hgb", "同基础控制：HGB", "同基础控制"),
    ("base_mlp", "同基础控制：MLP", "同基础控制"),
    ("ensemble_equal", "旧集成：等权", "旧集成参照"),
    ("ensemble_consensus_risk", "旧集成：分歧风险", "旧集成参照"),
    ("ensemble_stacked", "旧集成：学习权重", "旧集成参照"),
    ("original_A2_scores_common_account_reference_r1", "原 A2 分数共同参照", "原 A2 共同参照"),
]
COLORS = {"组合设计": "#216B78", "同基础控制": "#6F7397",
          "旧集成参照": "#B18B59", "原 A2 共同参照": "#414B57"}


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    before = sha(CSV)
    table = pd.read_csv(CSV)
    h2 = table.loc[table.year.eq(2025)].set_index("policy")
    assert not h2.index.duplicated().any()
    assert set(h2.index) == {row[0] for row in ROWS}
    assert h2.days.eq(128).all()
    assert h2.uncertified_days.eq(0).all()
    h2 = h2.loc[[row[0] for row in ROWS]]
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    if not font_path.exists():
        raise FileNotFoundError("Expected Microsoft YaHei font for legible Chinese chart labels")
    font_manager.fontManager.addfont(str(font_path))
    plt.rcParams.update({
        "font.family": font_manager.FontProperties(fname=str(font_path)).get_name(),
        "font.size": 12, "axes.unicode_minus": False, "figure.facecolor": "white",
        "axes.facecolor": "white", "savefig.facecolor": "white",
        "axes.edgecolor": "#D3D7DC", "axes.labelcolor": "#303841",
        "text.color": "#202A34", "xtick.color": "#535F6B", "ytick.color": "#27323D",
    })
    figure, axes = plt.subplots(1, 3, figsize=(18, 10.7), sharey=True)
    figure.subplots_adjust(left=.225, right=.978, bottom=.185, top=.805, wspace=.16)
    y = np.arange(len(ROWS))
    colors = [COLORS[row[2]] for row in ROWS]
    fields = [
        ("indicative_net_return", "净记账收益", (-12, 44), [-10, 0, 10, 20, 30, 40]),
        ("indicative_max_drawdown", "最大回撤", (-26, 1), [-25, -20, -15, -10, -5, 0]),
        ("mean_actual_cash", "平均实际现金", (0, 80), [0, 20, 40, 60, 80]),
    ]
    for axis, (field, title, limits, ticks) in zip(axes, fields):
        values = h2[field].to_numpy(float) * 100
        assert np.isfinite(values).all()
        axis.barh(y, values, color=colors, height=.66, linewidth=0, zorder=3)
        axis.set_title(title, fontsize=16, pad=17, fontweight="medium")
        axis.set_xlim(limits)
        axis.set_xticks(ticks)
        axis.xaxis.set_major_formatter(ticker.PercentFormatter(xmax=100, decimals=0))
        axis.grid(axis="x", color="#E8EBEF", linewidth=.75, zorder=0)
        axis.axvline(0, color="#A7B0B9", linewidth=.9, zorder=2)
        axis.tick_params(axis="x", labelsize=11, length=0, pad=9)
        axis.tick_params(axis="y", length=0, pad=13)
        for name in ["top", "right", "left"]:
            axis.spines[name].set_visible(False)
        for boundary in [7.5, 10.5, 13.5]:
            axis.axhline(boundary, color="#D7DCE2", linewidth=.85, zorder=1)
        for row_y, value in zip(y, values):
            offset = .7 if field == "indicative_net_return" else .45 if field == "indicative_max_drawdown" else 1.1
            # Negative return labels use the empty positive side, away from long row names.
            label_x = .8 if field == "indicative_net_return" and value < 0 else value + (offset if value >= 0 else -offset)
            label_align = "left" if value >= 0 or field == "indicative_net_return" else "right"
            axis.text(label_x, row_y,
                      f"{value:.2f}%", ha=label_align, va="center",
                      fontsize=11.2, color="#27323D", clip_on=False)
    axes[0].set_yticks(y, [row[1] for row in ROWS], fontsize=12.7)
    axes[0].set_ylim(len(ROWS)-.4, -.7)
    figure.text(.047, .955, "2025H2｜固定策略的共同账户比较", fontsize=23, fontweight="medium", va="top")
    figure.text(.047, .907, "128 个账户日 · 2025-07-01 至 12-31 · 初始现金 100 万美元 · 单边成本 10bp",
                fontsize=13.3, color="#4E5A66", va="top")
    figure.legend(handles=[Patch(facecolor=color, label=label) for label, color in COLORS.items()],
                  loc="upper left", bbox_to_anchor=(.215, .884), ncol=4,
                  frameon=False, fontsize=12, handlelength=1.45, columnspacing=1.9)
    figure.text(.047, .113, "阅读口径：按预设方法顺序排列，不按收益排名；现金为 128 个账户日的实际现金比例均值，并非信号目标现金。",
                fontsize=11.8, color="#45525F", va="top")
    figure.text(.047, .077, "研究边界：价格指数账本核对不等于股东总回报或真实结算认证；方案差异及费用、现金差异不证明模型互补的因果收益。",
                fontsize=11.8, color="#45525F", va="top")
    figure.text(.047, .041, "数据：本批 ALL_COMPARISONS.csv；8 个组合设计、3 个同基础控制、3 个旧集成及原 A2 分数共同参照。",
                fontsize=10.7, color="#74808B", va="top")
    figure.savefig(OUTPUT, dpi=180)
    plt.close(figure)
    assert sha(CSV) == before, "Comparison table changed during plotting"
    print(f"Saved {OUTPUT}; source SHA256 unchanged: {before}")


if __name__ == "__main__":
    main()
