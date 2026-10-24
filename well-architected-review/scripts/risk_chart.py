"""Chart the risk counts per pillar from reports/<prefix>-risks.json (written after a milestone).

    .venv/Scripts/python well-architected-review/scripts/risk_chart.py baseline
    .venv/Scripts/python well-architected-review/scripts/risk_chart.py baseline         --pillars security,reliability,costOptimization --name post-3-pillars

Writes images/<prefix>-risks.png (or images/<name>.png): one stacked bar per pillar (high / medium /
no risk / not applicable), Framework lens and Serverless Lens side by side.
"""
import argparse
import json
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REVIEW_DIR = Path(__file__).resolve().parent.parent

PILLARS = [
    ("operationalExcellence", "Operational excellence"),
    ("security", "Security"),
    ("reliability", "Reliability"),
    ("performance", "Performance efficiency"),
    ("costOptimization", "Cost optimization"),
    ("sustainability", "Sustainability"),
]
# Status colors (state, not series): fixed, always paired with a text label
RISKS = [
    ("HIGH", "High risk", "#d03b3b", "white"),
    ("MEDIUM", "Medium risk", "#fab219", "#0b0b0b"),
    ("NONE", "No risk", "#0ca30c", "white"),
    ("NOT_APPLICABLE", "Not applicable", "#c3c2b7", "#0b0b0b"),
]
SURFACE, INK, INK_2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"


def draw(ax, rows, title, x_max, n_rows):
    pillars = [(pid, name) for pid, name in PILLARS if any(r["pillar"] == pid for r in rows)]
    counts = {pid: Counter(r["risk"] for r in rows if r["pillar"] == pid) for pid, _ in pillars}
    total = Counter(r["risk"] for r in rows)
    for y, (pid, _) in enumerate(pillars):
        left = 0
        for risk, _, color, text in RISKS:
            n = counts[pid][risk]
            if not n:
                continue
            # 2px surface gap between segments
            ax.barh(y, n, left=left, height=0.62, color=color, edgecolor=SURFACE, linewidth=2)
            ax.text(left + n / 2, y, str(n), ha="center", va="center", color=text,
                    fontsize=10, fontweight="bold")
            left += n
        ax.text(left + 0.25, y, f"{left}", ha="left", va="center", color=MUTED, fontsize=9)
    ax.set_yticks(range(len(pillars)), [name for _, name in pillars], color=INK_2, fontsize=10)
    # Same scale and bar size in both panels: one question is the same length everywhere
    ax.set_ylim(n_rows - 0.5, -0.5)
    ax.set_xlim(0, x_max)
    ax.set_xticks([])
    for side in ("top", "right", "bottom"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color("#c3c2b7")
    ax.tick_params(axis="y", length=0)
    summary = f"{len(rows)} questions · {total['HIGH']} high · {total['MEDIUM']} medium · {total['NONE']} no risk"
    # Fixed offsets in points, so titles don't collide when the panel is short
    ax.annotate(title, (0, 1), xycoords="axes fraction", xytext=(0, 24), textcoords="offset points",
                fontsize=12, fontweight="bold", color=INK)
    ax.annotate(summary, (0, 1), xycoords="axes fraction", xytext=(0, 7), textcoords="offset points",
                fontsize=9.5, color=INK_2)


def main(prefix, pillars, name, title):
    data = json.loads((REVIEW_DIR / "reports" / f"{prefix}-risks.json").read_text(encoding="utf-8"))
    if pillars:
        data = {lens: [r for r in rows if r["pillar"] in pillars] for lens, rows in data.items()}
    n_rows = max(len({r["pillar"] for r in rows}) for rows in data.values())
    fig, axes = plt.subplots(1, 2, figsize=(12, 1.6 + 0.57 * n_rows), facecolor=SURFACE,
                             gridspec_kw={"wspace": 0.5})
    fig.subplots_adjust(top=1 - 1.05 / (1.6 + 0.57 * n_rows), bottom=0.85 / (1.6 + 0.57 * n_rows),
                        left=0.15, right=0.98)
    x_max = max(Counter(r["pillar"] for r in rows).most_common(1)[0][1] for rows in data.values()) + 1.5
    for ax in axes:
        ax.set_facecolor(SURFACE)
    draw(axes[0], data["wellarchitected"], "AWS Well-Architected Framework lens", x_max, n_rows)
    draw(axes[1], data["serverless"], "Serverless Lens", x_max, n_rows)
    present = {r["risk"] for rows in data.values() for r in rows}
    shown = [risk for risk in RISKS if risk[0] in present]
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for _, _, c, _ in shown]
    fig.legend(handles, [label for _, label, _, _ in shown], loc="lower center", ncol=len(shown),
               bbox_to_anchor=(0.5, 0.045),
               frameon=False, fontsize=10, labelcolor=INK_2)
    fig.suptitle(title, x=0.02, ha="left", fontsize=13, fontweight="bold", color=INK, y=0.99)
    fig.text(0.02, 0.0, f"Milestone: {prefix} · github.com/sriram-um/aws-serverless-application",
             fontsize=8.5, color=MUTED)
    out = REVIEW_DIR / "images" / f"{name or prefix + '-risks'}.png"
    out.parent.mkdir(exist_ok=True)
    fig.savefig(out, dpi=150, bbox_inches="tight", pad_inches=0.3, facecolor=SURFACE)
    print(out.relative_to(REVIEW_DIR))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("prefix", nargs="?", default="baseline")
    parser.add_argument("--pillars", help="comma-separated pillar ids to include (default: all)")
    parser.add_argument("--name", help="output image name (default: <prefix>-risks)")
    parser.add_argument("--title", default="Well-Architected review of aws-serverless-application: "
                                           "questions by risk, per pillar")
    args = parser.parse_args()
    main(args.prefix, args.pillars.split(",") if args.pillars else None, args.name, args.title)
