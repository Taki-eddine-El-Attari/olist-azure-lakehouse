"""Figures for the project report (docs/report/rapport.html), from the local Gold tables. Run in Docker:

    docker compose run --rm dev sh -c "pip install -q matplotlib==3.10.6 && python docs/report/make_figures.py"

matplotlib is only needed here (same version as the serverless environment), so it is not in requirements.txt.
The backtest and the final fits are re-run: same data and seed as olist.ml.train, so the same numbers.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402
from sklearn.metrics import average_precision_score, precision_recall_curve  # noqa: E402

from olist.ml.features import CATEGORICAL, FEATURES, load, split  # noqa: E402
from olist.ml.train import backtest, candidates, fit, labels  # noqa: E402
from olist.spark import get_spark  # noqa: E402

OUT = Path(__file__).parent / "figures"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
# Reference categorical palette (dataviz skill), fixed per model; the baseline is a gray reference line.
STYLE = {
    "lightgbm_no_recent": ("LightGBM sans taux récent (champion)", "#2a78d6", 2.8, "-"),
    "logistic_regression": ("Régression logistique", "#eb6834", 2.0, "-"),
    "lightgbm": ("LightGBM", "#1baf7a", 2.0, "-"),
    "lightgbm_weighted": ("LightGBM pondéré", "#eda100", 2.0, "-"),
    "baseline_rule": ("Règle : km par jour promis", "#8a8986", 2.0, "--"),
}
plt.rcParams.update({
    "font.size": 10, "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED,
    "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.8, "legend.frameon": False, "savefig.dpi": 200,
})


COMMA = FuncFormatter(lambda v, _: f"{v:g}".replace(".", ","))  # French decimal comma on axes


def fr(v, digits):
    return f"{v:.{digits}f}".replace(".", ",")


def save(fig, name):
    fig.savefig(OUT / name, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def architecture():
    fig, ax = plt.subplots(figsize=(11, 5.2))
    ax.set_xlim(0, 110)
    ax.set_ylim(0, 52)
    ax.axis("off")

    def group(x, y, w, h, title, color, bottom=False):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4,rounding_size=1.5",
                                    fc=color + "14", ec=color, lw=1.4))
        # Title at the bottom when an arrow enters the group through the top.
        ty, va = (y + 0.6, "bottom") if bottom else (y + h - 1.6, "top")
        ax.text(x + 1, ty, title, fontsize=9.5, fontweight="bold", color=color, va=va)

    def box(x, y, w, h, text):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.3,rounding_size=1",
                                    fc="white", ec=MUTED, lw=1))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=8.6, color=INK)

    def arrow(x1, y1, x2, y2, dashed=False):
        ax.annotate("", (x2, y2), (x1, y1), arrowprops=dict(arrowstyle="-|>", color=MUTED, lw=1.2,
                                                            linestyle="--" if dashed else "-"))

    box(1, 22, 11, 8, "9 CSV\nKaggle Olist")
    group(16, 16, 15, 20, "ADLS Gen2", "#1baf7a", bottom=True)
    box(18, 23, 11, 7, "landing/olist\n+ archive")
    group(16, 38, 54, 12, "Azure Data Factory · pl_olist_daily", "#eb6834")
    box(18, 40, 14, 6, "Get Metadata\n9 fichiers ?")
    box(36, 40, 14, 6, "Job Databricks\nolist_pipeline")
    box(54, 40, 14, 6, "Copy vers\nlanding/archive")
    group(34, 2, 50, 33, "Azure Databricks serverless · Unity Catalog", "#2a78d6", bottom=True)
    box(36, 21, 10, 8, "01 Bronze\nschéma\nexplicite")
    box(48, 21, 10, 8, "02 Silver\n23 contrôles\nquarantaine")
    box(60, 21, 10, 8, "03 Gold\nétoile\n11 contrôles")
    box(72, 21, 10, 8, "05 Scoring\nchampion")
    box(48, 7, 16, 8, "04 Entraînement\nbacktest + MLflow")
    box(68, 7, 14, 8, "olist.ml.\nlate_delivery\n@champion")
    group(88, 14, 21, 22, "Power BI", "#6250d6")
    box(90, 19, 17, 10, "4 pages\nSQL warehouse\nmode Import")

    arrow(12, 26, 18, 26)
    arrow(29, 30, 25, 40)
    arrow(32, 43, 36, 43)
    arrow(50, 43, 54, 43)
    arrow(43, 40, 41, 29)
    arrow(46, 25, 48, 25)
    arrow(58, 25, 60, 25)
    arrow(70, 25, 72, 25)
    arrow(64, 11, 68, 11, dashed=True)
    arrow(77, 15, 77, 21, dashed=True)
    arrow(82, 25, 90, 24)
    arrow(29, 26, 36, 25)
    save(fig, "architecture.png")


def backtest_lift(lifts):
    months = list(lifts.index)
    fig, ax = plt.subplots(figsize=(9, 4.2))
    for name, (label, color, lw, ls) in STYLE.items():
        ax.plot(months, lifts[name], color=color, lw=lw, ls=ls, marker="o", ms=4, label=label)
    ax.axhline(1, color=MUTED, lw=1, ls=":")
    ax.text(len(months) - 1, 1.05, "hasard = 1", ha="right", fontsize=8.5, color=MUTED)
    ax.set_ylabel("Lift (PR-AUC / taux de retard du mois)")
    ax.set_xlabel("Mois prédit (modèle entraîné sur tout le passé)")
    ax.set_ylim(0, None)
    ax.yaxis.set_major_formatter(COMMA)
    ax.legend(loc="upper left", fontsize=8.5, ncol=2)
    save(fig, "backtest_lift.png")


def pr_curves(y_test, scores):
    fig, ax = plt.subplots(figsize=(7.5, 4.6))
    for name in ["lightgbm_no_recent", "logistic_regression", "baseline_rule"]:
        label, color, lw, ls = STYLE[name]
        precision, recall, _ = precision_recall_curve(y_test, scores[name])
        ap = average_precision_score(y_test, scores[name])
        ax.plot(recall, precision, color=color, lw=lw, ls=ls, label=f"{label} — PR-AUC {fr(ap, 3)}")
    ax.axhline(y_test.mean(), color=MUTED, lw=1, ls=":")
    ax.text(0.03, y_test.mean() - 0.009, f"taux de retard du test = {fr(y_test.mean(), 3)} (hasard)",
            ha="left", fontsize=8.5, color=MUTED)
    ax.set_xlabel("Rappel")
    ax.set_ylabel("Précision")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 0.2)
    ax.xaxis.set_major_formatter(COMMA)
    ax.yaxis.set_major_formatter(COMMA)
    ax.legend(loc="upper right", fontsize=8.5)
    save(fig, "pr_curve_test.png")


def importance(model):
    used = list(model[0].transformers[0][2]) + CATEGORICAL
    gain = model[-1].booster_.feature_importance("gain")
    share = sorted(zip(used, 100 * gain / gain.sum()), key=lambda t: t[1])
    fig, ax = plt.subplots(figsize=(7.5, 5))
    ax.barh([n for n, _ in share], [v for _, v in share], color="#2a78d6", height=0.6)
    for i, (_, v) in enumerate(share):
        ax.text(v + 0.2, i, f"{fr(v, 1)} %", va="center", fontsize=8, color=MUTED)
    ax.set_xlabel("Part du gain total (%)")
    ax.xaxis.set_major_formatter(COMMA)
    ax.grid(axis="y", visible=False)
    save(fig, "feature_importance.png")


def main():
    OUT.mkdir(exist_ok=True)
    architecture()
    df = load(get_spark("olist-report"))
    lifts, _ = backtest(df)
    backtest_lift(lifts)
    parts = split(df)
    y_fit, y_test = labels(parts["fit"]), labels(parts["test"])
    scores, models = {}, {}
    for name, model in candidates(y_fit).items():
        models[name] = fit(name, model, parts["fit"][FEATURES], y_fit)
        scores[name] = models[name].predict_proba(parts["test"][FEATURES])[:, 1]
    pr_curves(y_test, scores)
    importance(models["lightgbm_no_recent"])
    print(lifts.round(2).to_string())
    print({n: round(average_precision_score(y_test, s), 3) for n, s in scores.items()})


if __name__ == "__main__":
    main()
