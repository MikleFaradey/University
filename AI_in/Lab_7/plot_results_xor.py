from pathlib import Path
import csv
import json
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent
with (ROOT / "history.csv").open(encoding="utf-8") as file:
    history = list(csv.DictReader(file))
with (ROOT / "predictions.csv").open(encoding="utf-8") as file:
    samples = list(csv.DictReader(file))
model = json.loads((ROOT / "model.json").read_text(encoding="utf-8"))
epochs = [int(row["epoch"]) for row in history]
errors = [float(row["E"]) for row in history]
wrong = [int(row["wrong"]) for row in history]
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11})
fig, axes = plt.subplots(2, 1, figsize=(7.0, 5.5), sharex=True)
axes[0].semilogy(epochs, errors, color="black")
axes[0].axhline(model["epsilon"], color="gray", linestyle="--", label="Threshold: 0.1")
axes[0].set_ylabel("Error E(k)")
axes[0].legend()
axes[1].plot(epochs, wrong, color="black")
axes[1].set_xlabel("Epoch k")
axes[1].set_ylabel("Incorrect predictions")
for ax in axes:
    ax.grid(True, alpha=0.3)
fig.tight_layout()
fig.savefig(ROOT / "learning.png", dpi=240)
plt.close(fig)
coordinates = np.linspace(0.0, 1.0, 401)
x1, x2 = np.meshgrid(coordinates, coordinates)
hidden = []
for bias, w1, w2 in model["hidden_weights"]:
    hidden.append(np.tanh((bias + w1 * x1 + w2 * x2) / 2.0))
b0, b1, b2 = model["output_weights"]
output = np.tanh((b0 + b1 * hidden[0] + b2 * hidden[1]) / 2.0)
fig, ax = plt.subplots(figsize=(6.2, 5.7))
ax.contourf(x1, x2, output, levels=[-1, 0, 1], colors=["#eeeeee", "#c5d7e8"])
ax.contour(x1, x2, output, levels=[0], colors="black", linewidths=1.3)
for label, marker in [("X", "x"), ("O", "o")]:
    points = [row for row in samples if row["target_class"] == label]
    xs = [float(row["x1"]) for row in points]
    ys = [float(row["x2"]) for row in points]
    if label == "X":
        ax.scatter(xs, ys, marker=marker, s=90, color="black", label="Class X", zorder=3)
    else:
        ax.scatter(xs, ys, s=85, facecolors="white", edgecolors="black", label="Class O")
ax.set_xlim(-0.04, 1.04)
ax.set_ylim(1.04, -0.04)
ax.set_xticks([0, 0.25, 0.5, 0.75, 1])
ax.set_yticks([0, 0.25, 0.5, 0.75, 1])
ax.set_xlabel(r"$x_1$")
ax.set_ylabel(r"$x_2$")
ax.set_aspect("equal")
ax.grid(True, alpha=0.25)
ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.13), ncol=2)
fig.tight_layout()
fig.savefig(ROOT / "decision.png", dpi=240)
plt.close(fig)
