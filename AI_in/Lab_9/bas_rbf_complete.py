from itertools import product, combinations
from math import exp
from pathlib import Path
import csv

ETA = 0.3
MAX_EPOCHS = 1000
ROOT = Path(__file__).resolve().parent

def target_function(x):
    x1, x2, x3, x4 = x
    return int((not (x3 or x4) and not x1) or x2)

def make_truth_table():
    return [(x, target_function(x)) for x in product((0, 1), repeat=4)]

def choose_centers(table):
    zeros = [x for x, target in table if target == 0]
    ones = [x for x, target in table if target == 1]
    return zeros if len(zeros) <= len(ones) else ones

def radial_basis(x, center):
    return exp(-sum((xi - ci) ** 2 for xi, ci in zip(x, center)))

def features(x, centers):
    return [1.0] + [radial_basis(x, center) for center in centers]

def output_vector(matrix, weights):
    return [int(sum(w * p for w, p in zip(weights, row)) >= 0) for row in matrix]

def evaluate(matrix, targets, weights):
    outputs = output_vector(matrix, weights)
    error = sum((target - output) ** 2 for target, output in zip(targets, outputs))
    return error, outputs

def teach_model(matrix, targets, indices, eta=ETA, max_epochs=MAX_EPOCHS):
    weights = [0.0] * len(matrix[0])
    error, outputs = evaluate(matrix, targets, weights)
    history = [(0, error, weights.copy(), outputs)]
    if error == 0:
        return weights, history
    for epoch in range(1, max_epochs + 1):
        changed = False
        for index in indices:
            row = matrix[index]
            net = sum(w * p for w, p in zip(weights, row))
            output = int(net >= 0)
            delta = targets[index] - output
            if delta != 0:
                changed = True
                for j in range(1, len(weights)):
                    weights[j] += eta * delta * row[j]
                weights[0] += eta * delta
        error, outputs = evaluate(matrix, targets, weights)
        history.append((epoch, error, weights.copy(), outputs))
        if error == 0 or not changed:
            break
    return weights, history

def find_minimum_sample(matrix, targets):
    tested = 0
    for size in range(1, len(matrix) + 1):
        for indices in combinations(range(len(matrix)), size):
            tested += 1
            weights, history = teach_model(matrix, targets, indices)
            if history[-1][1] == 0:
                return indices, weights, history, tested
    raise RuntimeError("No successful training subset was found")

def save_history(filename, history):
    weight_count = len(history[0][2])
    output_count = len(history[0][3])
    header = ["epoch", "E(k)"] + [f"v{i}" for i in range(weight_count)]
    header += [f"y{i + 1}" for i in range(output_count)]
    with (ROOT / filename).open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(header)
        for epoch, error, weights, outputs in history:
            writer.writerow([epoch, error, *weights, *outputs])

def print_history(title, history):
    print("\n" + title)
    for epoch, error, weights, outputs in history:
        values = ", ".join(f"{weight:.8f}" for weight in weights)
        print(f"k={epoch}; E={error}; v=({values}); y={outputs}")

def save_plot(full_history, minimum_history):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot([r[0] for r in full_history], [r[1] for r in full_history], "o-", label="Full sample")
    xs = [r[0] for r in minimum_history]
    ys = [r[1] for r in minimum_history]
    ax.plot(xs, ys, "s--", label="Minimum sample")
    ax.set_xlabel("Epoch k")
    ax.set_ylabel("E(k): errors on all 16 vectors")
    ax.set_xticks(sorted({r[0] for r in full_history + minimum_history}))
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(ROOT / "rbf_error.png", dpi=200)
    plt.close(fig)

def main():
    table = make_truth_table()
    targets = [target for x, target in table]
    centers = choose_centers(table)
    matrix = [features(x, centers) for x, target in table]
    print("RBF: lab 4, variant 2")
    print("F = (not (x3 or x4) and not x1) or x2")
    print(f"J0={targets.count(0)}; J1={targets.count(1)}; J={len(centers)}")
    print(f"Centers: {centers}")
    weights, full_history = teach_model(matrix, targets, range(len(table)))
    if full_history[-1][1] != 0:
        raise RuntimeError("Full-sample training did not converge")
    print_history("Training on all 16 vectors", full_history)
    indices, minimum_weights, minimum_history, tested = find_minimum_sample(matrix, targets)
    print(f"\nMinimum sample size: {len(indices)}; tested subsets: {tested}")
    for index in indices:
        print(f"Row {index + 1}: x={table[index][0]}; t={targets[index]}")
    print_history("Training on the minimum sample", minimum_history)
    print("\nFull truth-table validation")
    for i, (x, target) in enumerate(table):
        first = full_history[-1][3][i]
        second = minimum_history[-1][3][i]
        print(f"x={x}; t={target}; y_full={first}; y_minimum={second}")
    save_history("rbf_history.csv", full_history)
    save_history("rbf_min_history.csv", minimum_history)
    save_plot(full_history, minimum_history)

if __name__ == "__main__":
    main()
