"""Plot saved complete account paths; no model evaluation or new strategy run."""
from pathlib import Path
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def main():
    choices = [
        ("hgb_return_baseline", "Return baseline (HGB)", "#263238", "-"),
        ("joint_mlp", "Joint MLP", "#b84d6b", "-"),
        ("joint_rl_ensemble", "Joint RL, trained", "#1879b5", "-"),
        ("joint_rl_zero_control", "RL zero-update control", "#888888", "--"),
    ]
    paths = {}
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(11, 7.6), sharex=True,
                                      gridspec_kw={"height_ratios": [2.6, 1]})
    for policy, label, color, style in choices:
        folder = ROOT / "evaluation_2025/cost_10" / policy
        d = pd.read_parquet(folder / "daily.parquet").sort_values("date")
        assert len(d) == 250 and d.certified_nav.notna().all() and d.valuation_status.eq("certified").all()
        initial = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))["initial_cash"]
        cumulative = d.certified_nav / initial - 1
        paths[policy] = pd.Series(cumulative.to_numpy(), index=d.date)
        top.plot(d.date, cumulative * 100, label=label, color=color, linestyle=style, linewidth=1.7)
    paired = (paths["joint_rl_ensemble"] - paths["joint_rl_zero_control"]) * 100
    bottom.plot(paired.index, paired, color="#1879b5", linewidth=1.6)
    bottom.axhline(0, color="#666666", linewidth=.8)
    bottom.annotate(f"{paired.iloc[-1]:+.2f} pp", xy=(paired.index[-1], paired.iloc[-1]),
                    xytext=(-58, 11), textcoords="offset points", color="#14577e", fontweight="bold")
    top.axhline(0, color="#666666", linewidth=.8)
    top.set_ylabel("Net index-account return (%)")
    bottom.set_ylabel("RL minus zero\n(return pp)")
    top.set_title("2025 validation: the same complete 250-session window", loc="left", fontsize=14, pad=16)
    top.legend(loc="upper left", fontsize=9, frameon=False)
    for ax in (top, bottom):
        ax.grid(axis="y", alpha=.2)
        ax.spines[["top", "right"]].set_visible(False)
        ax.margins(x=.025)
    fig.text(.08, .025, "Saved paths only | 10 bp per side | Complete index-NAV qualification, not shareholder total return\n"
             "RL zero is the matched update control; it is not a matched MLP ablation. No dates or stocks removed.",
             fontsize=9, color="#555555")
    fig.tight_layout(rect=(.02, .09, .99, .99))
    fig.savefig(HERE / "VALIDATION_2025_TRAJECTORIES.png", dpi=170)
    plt.close(fig)
    print("Saved economic_review/VALIDATION_2025_TRAJECTORIES.png")


if __name__ == "__main__":
    main()
