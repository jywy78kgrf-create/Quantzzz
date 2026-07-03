"""Phase 3 charts -> report/figs/*.png (static, light surface).

Style: single-hue marks (identity is carried by position/labels, not color),
thin bars, recessive grid, direct labels, no dual axes.
Palette: validated default from the dataviz reference (blue #2a78d6).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
FIGS = Path(__file__).resolve().parent.parent / "report" / "figs"
FIGS.mkdir(parents=True, exist_ok=True)

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
BLUE = "#2a78d6"
GRAY = "#c9c8c2"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "text.color": INK, "axes.edgecolor": INK2,
    "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
})

BUCKET_ORDER = ["GHOST", "TEST_RIG", "DORMANT", "LOW_ACTIVITY",
                "ACTIVE_LEGITIMATE", "DUPLICATE", "MEMECOIN"]
LABELS = {"GHOST": "Ghost", "TEST_RIG": "Test rig", "DORMANT": "Dormant",
          "LOW_ACTIVITY": "Low activity", "DUPLICATE": "Duplicate",
          "MEMECOIN": "Memecoin artifact",
          "ACTIVE_LEGITIMATE": "Active-legitimate"}


def bucket_distribution() -> None:
    d = json.load(open(OUT / "headline_numbers.json"))["buckets"]
    fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.4), sharey=True)
    for ax, key, title in [
            (axes[0], "share_sellers", "Share of sellers"),
            (axes[1], "share_volume", "Share of all-time volume (corrected)")]:
        vals = [d[b][key] * 100 for b in BUCKET_ORDER]
        y = range(len(BUCKET_ORDER))
        bars = ax.barh(y, vals, height=0.62, color=BLUE, zorder=3)
        hero = BUCKET_ORDER.index("ACTIVE_LEGITIMATE")
        for i, b in enumerate(bars):
            b.set_color(BLUE if i == hero else GRAY)
        ax.set_yticks(y, [LABELS[b] for b in BUCKET_ORDER])
        ax.invert_yaxis()
        ax.set_title(title, loc="left", fontsize=11, color=INK)
        ax.xaxis.set_visible(False)
        for i, v in enumerate(vals):
            ax.text(v + max(vals) * 0.015, i, f"{v:.1f}%".replace(".0%", "%"),
                    va="center", fontsize=9,
                    color=INK if i == hero else INK2,
                    fontweight="bold" if i == hero else "normal")
        ax.set_xlim(0, max(vals) * 1.18)
    fig.suptitle("x402 sellers by classification bucket (n = 163,417)",
                 x=0.01, ha="left", fontsize=12, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(FIGS / "bucket_distribution.png", dpi=200)
    plt.close(fig)


def concentration_curve() -> None:
    d = json.load(open(OUT / "concentration.json"))
    xs = [p[0] for p in d["curve_topN_cumshare"]]
    ys = [p[1] * 100 for p in d["curve_topN_cumshare"]]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(xs, ys, color=BLUE, lw=2, zorder=3)
    ax.set_xscale("log")
    ax.set_xlabel("Top N sellers (log scale)")
    ax.set_ylabel("Cumulative share of volume")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.grid(True, color="#e8e7e3", lw=0.6, zorder=0)
    for n, share in [(10, d["top10_share_all"]), (100, d["top100_share_all"])]:
        ax.scatter([n], [share * 100], color=BLUE, s=42, zorder=4)
        ax.annotate(f"top {n}: {share*100:.0f}%", (n, share * 100),
                    textcoords="offset points", xytext=(8, -12),
                    fontsize=9.5, color=INK)
    ax.set_title("Volume concentration: cumulative share by seller rank\n"
                 "(corrected all-time volume, 163,417 sellers)",
                 loc="left", fontsize=11.5, fontweight="bold")
    fig.tight_layout()
    fig.savefig(FIGS / "volume_concentration.png", dpi=200)
    plt.close(fig)


def cohort_chart() -> None:
    d = json.load(open(OUT / "cohort_survival.json"))["cohorts"]
    months = [m for m, c in sorted(d.items()) if c["n"] >= 5]
    rates = [d[m]["survival_rate"] * 100 for m in months]
    ns = [d[m]["n"] for m in months]
    fig, ax = plt.subplots(figsize=(7, 3.8))
    ax.bar(range(len(months)), rates, width=0.62, color=BLUE, zorder=3)
    ax.set_xticks(range(len(months)),
                  [f"{m[2:]}\nn={n}" for m, n in zip(months, ns)], fontsize=8.5)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.grid(True, axis="y", color="#e8e7e3", lw=0.6, zorder=0)
    for i, r in enumerate(rates):
        ax.text(i, r + 0.6, f"{r:.1f}%", ha="center", fontsize=8.5, color=INK)
    ax.set_ylim(0, max(rates) * 1.3 + 2)
    ax.set_title("New-seller cohort survival: % active ≥60 days after first transfer\n"
                 "(seeded control sample; cohorts n<5 hidden, <60d old excluded)",
                 loc="left", fontsize=10.5, fontweight="bold")
    fig.tight_layout()
    fig.savefig(FIGS / "cohort_survival.png", dpi=200)
    plt.close(fig)


def liveness_funnel() -> None:
    d = json.load(open(OUT / "liveness_summary.json"))["bazaar"]
    steps = [("Listed resources probed", d["probed"]),
             ("Answered (any HTTP status)", d["responded"]),
             ("Returned HTTP 402", d["http_402"]),
             ("Valid x402 payment requirements", d["valid_x402_402"])]
    fig, ax = plt.subplots(figsize=(7.5, 3.0))
    y = range(len(steps))
    vals = [s[1] for s in steps]
    colors = [GRAY, GRAY, GRAY, BLUE]
    ax.barh(y, vals, height=0.6, color=colors, zorder=3)
    ax.set_yticks(y, [s[0] for s in steps])
    ax.invert_yaxis()
    ax.xaxis.set_visible(False)
    for i, v in enumerate(vals):
        pct = v / vals[0] * 100
        ax.text(v + vals[0] * 0.012, i, f"{v:,}  ({pct:.0f}%)",
                va="center", fontsize=9.5,
                color=INK if i == len(vals) - 1 else INK2,
                fontweight="bold" if i == len(vals) - 1 else "normal")
    ax.set_xlim(0, vals[0] * 1.35)
    fig.suptitle("Does the endpoint answer the phone? Bazaar-listed resources\n"
                 "(unpaid GET/POST probe; capped 10 per origin; no payments)",
                 x=0.02, ha="left", fontsize=11, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(FIGS / "liveness_funnel.png", dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    bucket_distribution()
    concentration_curve()
    cohort_chart()
    liveness_funnel()
    print("wrote", sorted(p.name for p in FIGS.glob("*.png")))
    sys.exit(0)
