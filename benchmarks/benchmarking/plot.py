from pathlib import Path
from typing import Any
from typing import Dict

import matplotlib
import matplotlib.patches as mpatches
import numpy as np
from matplotlib import pyplot as plt

matplotlib.use("agg")


def get_data(result) -> Dict[str, Any]:
    results = {}

    for case in result:
        for benchmark in case["benchmarks"]:
            if "metadata" in benchmark:
                name = benchmark["metadata"]["name"]
            else:
                name = case["metadata"]["name"]
            data = []
            for run in benchmark["runs"]:
                data.extend(run.get("values", []))
            results[name] = np.array(data, dtype=np.float64)

    return results


def remove_outliers(values, m=2):
    return values[abs(values - np.mean(values)) < m * np.std(values)]


def plot_diff_pair(ax, ref, head, names, outlier_rejection=True):
    master_data = []
    all_data = []
    means = []
    for name in names:
        ref_values = ref[name]
        head_values = head[name]
        if outlier_rejection:
            ref_values = remove_outliers(ref_values)
            head_values = remove_outliers(head_values)
        means.append(np.mean(head_values))
        values = np.outer(ref_values, 1.0 / head_values).flatten()
        values.sort()
        idx = np.round(np.linspace(0, len(values) - 1, 100)).astype(int)
        all_data.append(values[idx])
        master_data.extend(values)

    all_data.append(master_data)
    violin = ax.violinplot(
        all_data,
        vert=False,
        showmeans=True,
        showmedians=False,
        showextrema=False,
        widths=1.0,
        quantiles=[[0.1, 0.9]] * len(all_data),
    )
    violin["cquantiles"].set_linestyle(":")
    for pc, mean in zip(violin["bodies"], means):
        if mean < 0.1:
            pc.set_facecolor("#ff0000")
        else:
            pc.set_facecolor("#0000ff")


def formatter(val, pos):
    return f"{val:.02f}x"


def plot_diff(ref, head, output_filename: Path, title: str) -> None:
    head_data = get_data(head.data)
    ref_data = get_data(ref.data)

    names = sorted(head_data.keys(), reverse=True)
    fig, axs = plt.subplots(figsize=(8, 2 + len(names) * 0.3), layout="constrained")
    plt.axvline(1.0)
    plot_diff_pair(axs, ref_data, head_data, names)
    names.append("ALL")
    axs.set_yticks(np.arange(len(names)) + 1, names)
    axs.set_ylim(0, len(names) + 1)
    axs.tick_params(axis="x", bottom=True, top=True, labelbottom=True, labeltop=True)
    axs.xaxis.set_major_formatter(formatter)
    axs.grid()
    axs.set_title(title)

    # Add legend for colors (red -> microbenchmark, blue -> macrobenchmark)

    axs.legend(
        handles=[
            mpatches.Patch(color="#ff0000", label="Microbenchmark"),
            mpatches.Patch(color="#0000ff", label="Macrobenchmark"),
        ],
        bbox_to_anchor=(0, 1.05),
    )

    plt.savefig(output_filename)
    plt.close()
