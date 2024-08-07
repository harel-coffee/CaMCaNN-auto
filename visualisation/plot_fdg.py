"""Plot force-directed layout of molecules."""
import re

DO_PY_FA = False

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from pathlib import Path
from scipy.stats import norm
if DO_PY_FA:
    from fa2 import ForceAtlas2

CACHE_POSITIONS = False
COLOUR_COUNTERION = True
HERE = Path(__file__).parent

if DO_PY_FA:
    kernel_df = pd.read_csv(HERE / "full_kernel.csv")
else:
    kernel_df = pd.read_csv(HERE / "fdg.csv")
kernel_mat = kernel_df.loc[:, "K0":].values

nist_pred_df = pd.read_csv(HERE / "uq_nist_pred.csv")
nist_pred_df["resid"] = nist_pred_df["log CMC"] - nist_pred_df["pred"]
# Normalise with respect to standard deviations
nist_pred_df["norm resid"] = nist_pred_df["resid"] / nist_pred_df["stddev"]
nist_pred_df["cdf"] = norm.cdf(nist_pred_df["norm resid"])
nist_pred_df["Above 95% CI"] = nist_pred_df["cdf"] > 0.95
nist_pred_df["Above 95% CI"].sum() / len(nist_pred_df["Above 95% CI"])

clusters_df = pd.read_csv(HERE / "clusters.csv")

def get_counterion(smiles: str) -> str:
    """Get the counterion for a smiles string"""
    pattern = r"\.(?P<counterion>\S+)"
    match = re.search(pattern, smiles)
    if match:
        counterion = match.group("counterion")
        if "." in counterion:
            multivalent_patt = r"(\[\S+[\+-]\])(\.\1)+"
            mulit_match = re.search(multivalent_patt, counterion)
            if mulit_match:
                return mulit_match.group(1)
            else:
                last_bit_patt = r"\S+\.(\S+)$"
                last_bit_match = re.search(last_bit_patt, counterion)
                if last_bit_match:
                    return last_bit_match.group(1)
                else:
                    raise ValueError("No match!")
        elif "C[N+]" in counterion or "CC" in counterion:
            return "Quat"
        else:
            return counterion
    else:
        if "+" in smiles and "-" in smiles:
            return "Zwitterionic"
        else:
            return "Nonionic"

def add_cols(df: pd.DataFrame):
    df["Counterion"] = df["SMILES"].apply(get_counterion)
    df["Source"] = ["Qin" if pd.isna(convertable) else "Complementary" for convertable in df["Convertable"]]

add_cols(kernel_df)
kernel_df = kernel_df.merge(nist_pred_df, on="Molecule name", how="left")
kernel_df["Above 95% CI"] = kernel_df["Above 95% CI"].apply(lambda x: x is True)
kernel_df["Cluster"] = clusters_df["cluster"]
kernel_df["Cluster"] = pd.Categorical(kernel_df["Cluster"])

if DO_PY_FA:
    forceatlas2 = ForceAtlas2(
        # Behavior alternatives
        outboundAttractionDistribution=False, # Dissuade hubs
        linLogMode=False,  # NOT IMPLEMENTED
        adjustSizes=False,  # Prevent overlap (NOT IMPLEMENTED)
        edgeWeightInfluence=10.0,
        # Performance
        jitterTolerance=1.0,  # Tolerance
        barnesHutOptimize=True,
        barnesHutTheta=1.2,
        multiThreaded=False,  # NOT IMPLEMENTED
        # Tuning
        scalingRatio=5.0,
        strongGravityMode=False,
        gravity=5.0,
        # Log
        verbose=True,
    )

    if CACHE_POSITIONS:
        try:
            positions = np.load(HERE / "positions.npy")
        except FileNotFoundError:
            positions = forceatlas2.forceatlas2(kernel_mat, iterations=5000)
            positions = np.array(positions)
            np.save(HERE / "positions.npy", positions)
    else:
        positions = forceatlas2.forceatlas2(kernel_mat, iterations=5000)
        positions = np.array(positions)

    kernel_df["x"] = positions[:, 0]
    kernel_df["y"] = positions[:, 1]

style = "Counterion" if COLOUR_COUNTERION else "Cluster"
to_plot = kernel_df if COLOUR_COUNTERION else kernel_df[(kernel_df["Cluster"] != -1) & (kernel_df["Counterion"] == "Nonionic")]

all_counterions = to_plot["Counterion"].unique()
counterion_order = list(all_counterions)

all_classes = to_plot["Cluster"].unique()
class_order = list(all_classes)

order = counterion_order if COLOUR_COUNTERION else class_order

fig, axs = plt.subplots(1, 2, sharex=True, sharey=True, subplot_kw=dict(aspect="equal"))
sns.scatterplot(
    to_plot,
    x="x",
    y="y",
    style=style,
    # size="Source",
    hue=style,
    # size_order=["NIST", "Qin"],
    hue_order=order,
    style_order=order,
    ax=axs[0],
    legend=True
)

just_qin = to_plot[to_plot["Source"] == "Qin"]

qin_counterion_counts = just_qin["Counterion"].value_counts()
include_kde = just_qin["Counterion"].apply(lambda x: qin_counterion_counts[x] > 2)

sns.kdeplot(
    just_qin[include_kde],
    x="x",
    y="y",
    hue=style,
    hue_order=order,
    ax=axs[1],
    fill=True,
    # bw_adjust=0.9,
    thresh=0.2,
    legend=False
)
sns.scatterplot(
    to_plot[to_plot["Above 95% CI"]],
    x="x",
    y="y",
    style=style,
    hue=style,
    # size="Source",
    # size_order=["NIST", "Qin"],
    hue_order=order,
    style_order=order,
    ax=axs[1],
    legend=False,
    zorder=10
)

sns.move_legend(axs[0], "upper center", bbox_to_anchor=(1.1,0), frameon=False, ncol=5)
for ax in axs:
    ax.set(xlabel="", ylabel="", xticklabels=[], yticklabels=[])
# plt.tight_layout()
axs[0].set_title("All molecules")
axs[1].set_title("Complementary data underpredictions\nsuperimposed on Qin distribution")
plt.savefig(HERE.parent / "paper" / "images" / "force-graph.pdf", bbox_inches="tight")