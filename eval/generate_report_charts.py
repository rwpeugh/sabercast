"""eval/generate_report_charts.py — Produce 2 new charts for the final report.

Outputs to eval/results/:
  rag_accuracy_by_category.png   — grouped bar chart of no-RAG vs RAG accuracy
  gap_position_hit_rate.png      — per-position precision bar chart with
                                    significance markers and random baseline

Both charts are referenced from docs/final_report/SABERCAST_FINAL_REPORT.md.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR  = PROJECT_ROOT / "eval" / "results"


def chart_rag_accuracy() -> None:
    rag = pd.read_csv(RESULTS_DIR / "rag_summary.csv")
    rag = rag[rag.category != "OVERALL"].copy()
    # Pleasant category order
    order = ["archetype", "trend", "combined_filter", "specific_stat", "general", "glossary"]
    rag["order"] = rag.category.map({c: i for i, c in enumerate(order)})
    rag = rag.sort_values("order").reset_index(drop=True)

    cats = rag.category.tolist()
    no_rag = rag.no_rag_acc.to_numpy() * 100
    rag_v  = rag.rag_acc.to_numpy() * 100
    n_per  = rag.n.to_numpy()

    x = np.arange(len(cats))
    width = 0.38

    fig, ax = plt.subplots(figsize=(9, 4.5))
    bars1 = ax.bar(x - width/2, no_rag, width, label="no-retrieval gpt-4o",
                   color="#cccccc", edgecolor="#444444")
    bars2 = ax.bar(x + width/2, rag_v, width, label="RAG-augmented gpt-4o",
                   color="#3a82cd", edgecolor="#1a55a0")

    # Bar labels with %
    for bars in (bars1, bars2):
        for bar in bars:
            h = bar.get_height()
            ax.annotate(f"{h:.0f}%", xy=(bar.get_x() + bar.get_width()/2, h),
                        xytext=(0, 3), textcoords="offset points",
                        ha="center", va="bottom", fontsize=9)

    pretty_labels = {
        "archetype":       "Archetype\nlookup",
        "trend":           "Trend\nlabels",
        "combined_filter": "Combined\nfilter",
        "specific_stat":   "Specific 2024\nstats",
        "general":         "General MLB\nknowledge",
        "glossary":        "Glossary",
    }
    labels = [f"{pretty_labels.get(c, c)}\n(n={n})" for c, n in zip(cats, n_per)]
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel("Accuracy (%)", fontsize=10)
    ax.set_ylim(0, 109)
    ax.set_title("RAG accuracy delta — vector retrieval vs no-retrieval gpt-4o\n"
                 "20 held-out questions · McNemar p = 0.0005 · overall +70 pp gain",
                 fontsize=11, loc="left", pad=12)
    ax.legend(loc="upper right", fontsize=9, framealpha=0.95)
    ax.set_axisbelow(True)
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    plt.tight_layout()
    out = RESULTS_DIR / "rag_accuracy_by_category.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"saved {out}")


def chart_hit_rate() -> None:
    hr = pd.read_csv(RESULTS_DIR / "gap_position_hit_rate_by_year.csv")
    # Drop too-small samples that we couldn't test
    hr = hr[hr.n >= 5].copy()
    # Sort by precision descending
    hr = hr.sort_values("precision", ascending=False).reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(9, 4.5))
    colors = []
    for _, r in hr.iterrows():
        if r.binom_p_vs_50pct < 0.05:
            colors.append("#3f9c3f")    # green — significant
        elif r.binom_p_vs_50pct < 0.10:
            colors.append("#c08c00")    # amber — trending
        else:
            colors.append("#999999")    # gray — not significant

    bars = ax.bar(hr.position, hr.precision * 100, color=colors, edgecolor="#333")

    # Significance markers
    for bar, p in zip(bars, hr.binom_p_vs_50pct):
        h = bar.get_height()
        mark = ""
        if p < 0.05:
            mark = "★"
        elif p < 0.10:
            mark = "·"
        label = f"{h:.0f}%"
        if mark:
            label = f"{mark} {label}"
        ax.annotate(label, xy=(bar.get_x() + bar.get_width()/2, h),
                    xytext=(0, 3), textcoords="offset points",
                    ha="center", va="bottom", fontsize=9, weight="bold" if mark == "★" else "normal")

    # Random baseline line
    ax.axhline(y=50, color="#444", linestyle="--", linewidth=1.2,
               label="Random baseline (50%)")

    ax.set_ylabel("Precision (%) — flagged-position underperformance hit-rate", fontsize=10)
    ax.set_ylim(0, 100)
    ax.set_xlabel("Top-1 flagged gap position", fontsize=10)
    ax.set_title("Position-level diagnostic precision — when Sabercast flags position P,\n"
                 "does that team's production at P underperform league average the following year?",
                 fontsize=11, loc="left", pad=12)
    ax.legend(loc="upper right", fontsize=9, framealpha=0.95)
    ax.set_axisbelow(True)
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    # Note about markers
    fig.text(0.02, -0.04, "★ = significant at p < 0.05 (binomial test vs 50% null) · "
                          "· = trending p < 0.10 · gray = not significant",
             fontsize=8.5, color="#444", ha="left")

    plt.tight_layout()
    out = RESULTS_DIR / "gap_position_hit_rate.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"saved {out}")


def main() -> None:
    chart_rag_accuracy()
    chart_hit_rate()


if __name__ == "__main__":
    main()
