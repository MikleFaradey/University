from math import tanh, sqrt
from pathlib import Path
from random import Random
import csv
import json

ROOT = Path(__file__).resolve().parent
DATA = [(0.00, 0.00, 1), (0.75, 0.00, -1), (1.00, 0.00, -1)]
DATA += [(0.00, 0.25, -1), (0.25, 0.25, 1), (0.50, 0.25, 1)]
DATA += [(1.00, 0.25, -1), (0.25, 0.50, -1), (0.50, 0.50, 1)]
DATA += [(0.75, 0.50, 1), (0.75, 0.75, 1), (1.00, 0.75, -1)]
DATA += [(0.00, 1.00, -1), (0.75, 1.00, -1)]
ETA = 0.1
EPSILON = 0.1
SEED = 2
MAX_EPOCHS = 100000

def activation(net):
    return tanh(net / 2.0)

def derivative(value):
    return 0.5 * (1.0 - value * value)

def forward(point, hidden_weights, output_weights):
    inputs = [1.0, point[0], point[1]]
    nets = [sum(a * x for a, x in zip(w, inputs)) for w in hidden_weights]
    hidden = [activation(net) for net in nets]
    net = output_weights[0] + sum(w * h for w, h in zip(output_weights[1:], hidden))
    return inputs, hidden, activation(net)

def deltas(target, hidden, output, output_weights):
    output_delta = derivative(output) * (target - output)
    hidden_delta = [derivative(h) * w * output_delta for h, w in zip(hidden, output_weights[1:])]
    return hidden_delta, output_delta

def evaluate(hidden_weights, output_weights):
    outputs = [forward(p, hidden_weights, output_weights)[2] for p in DATA]
    error = sqrt(sum((p[2] - y) ** 2 for p, y in zip(DATA, outputs)))
    wrong = sum((1 if y >= 0 else -1) != p[2] for p, y in zip(DATA, outputs))
    return outputs, error, wrong

def flatten(hidden_weights, output_weights):
    return [a for row in hidden_weights for a in row] + list(output_weights)

def save_csv(name, header, rows):
    with (ROOT / name).open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(header)
        writer.writerows(rows)

def main():
    random = Random(SEED)
    hidden_weights = [[random.uniform(-1.0, 1.0) for _ in range(3)] for _ in range(2)]
    output_weights = [random.uniform(-1.0, 1.0) for _ in range(3)]
    initial_weights = flatten(hidden_weights, output_weights)
    history = []
    trace = []
    first_correct = None
    order = list(range(len(DATA)))
    for epoch in range(MAX_EPOCHS + 1):
        outputs, error, wrong = evaluate(hidden_weights, output_weights)
        weights = flatten(hidden_weights, output_weights)
        history.append([epoch, error, error ** 2 / len(DATA), wrong, *weights, *outputs])
        if wrong == 0 and first_correct is None:
            first_correct = epoch
        if epoch % 1000 == 0 or (wrong == 0 and error <= EPSILON):
            print(f"epoch={epoch}; E={error:.8f}; wrong={wrong}/{len(DATA)}")
        if wrong == 0 and error <= EPSILON:
            break
        if epoch == MAX_EPOCHS:
            raise RuntimeError("Training did not reach the stopping criterion")
        random.shuffle(order)
        for step, index in enumerate(order, 1):
            point = DATA[index]
            inputs, hidden, output = forward(point, hidden_weights, output_weights)
            hidden_delta, output_delta = deltas(point[2], hidden, output, output_weights)
            before = flatten(hidden_weights, output_weights)
            for j in range(2):
                for i in range(3):
                    hidden_weights[j][i] += ETA * inputs[i] * hidden_delta[j]
            output_weights[0] += ETA * output_delta
            for j in range(2):
                output_weights[j + 1] += ETA * hidden[j] * output_delta
            if epoch == 0:
                after = flatten(hidden_weights, output_weights)
                signals = [*point, *hidden, output, *hidden_delta, output_delta]
                trace.append([step, index + 1, *signals, *before, *after])
    names = ["a01", "a11", "a21", "a02", "a12", "a22", "b0", "b1", "b2"]
    header = ["epoch", "E", "MSE", "wrong"] + names
    header += [f"y{i + 1}" for i in range(len(DATA))]
    save_csv("history.csv", header, history)
    header = ["step", "sample", "x1", "x2", "t", "h1", "h2", "y", "d1", "d2", "dout"]
    header += ["before_" + name for name in names] + ["after_" + name for name in names]
    save_csv("first_epoch.csv", header, trace)
    predictions = []
    for i, (point, output) in enumerate(zip(DATA, outputs), 1):
        target = "X" if point[2] == 1 else "O"
        predicted = "X" if output >= 0 else "O"
        predictions.append([i, *point, output, target, predicted, target == predicted])
        print(f"{i:2d}: x={point[:2]}; target={target}; y={output:.8f}; class={predicted}")
    header = ["id", "x1", "x2", "t", "y", "target_class", "predicted_class", "correct"]
    save_csv("predictions.csv", header, predictions)
    save_csv("samples.csv", ["id", "x1", "x2", "t"], [[i, *p] for i, p in enumerate(DATA, 1)])
    summary = {"seed": SEED, "eta": ETA, "epsilon": EPSILON, "epochs": epoch}
    summary.update({"E": error, "wrong": wrong, "first_correct_epoch": first_correct})
    summary.update({"initial_weights": initial_weights, "hidden_weights": hidden_weights})
    summary.update({"output_weights": output_weights, "weight_names": names})
    (ROOT / "model.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"First epoch with no classification errors: {first_correct}")
    print(f"Hidden weights: {hidden_weights}")
    print(f"Output weights: {output_weights}")

if __name__ == "__main__":
    main()
