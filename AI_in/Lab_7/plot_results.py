from pathlib import Path
import csv
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
with (ROOT / "training.csv").open(encoding="utf-8") as file:
    rows = list(csv.DictReader(file))
epochs = [int(row["k"]) for row in rows]
errors = [float(row["E"]) for row in rows]
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11})
fig, ax = plt.subplots(figsize=(7.0, 3.8))
ax.semilogy(epochs, errors, "o-", color="black", markersize=3)
ax.axhline(0.001, color="gray", linestyle="--", label="Threshold: 0.001")
ax.set_xlabel("Epoch k")
ax.set_ylabel("Error E(k)")
ax.grid(True, alpha=0.3)
ax.legend()
fig.tight_layout()
fig.savefig(ROOT / "error.png", dpi=240)
plt.close(fig)
