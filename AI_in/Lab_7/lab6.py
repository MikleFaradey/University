from math import tanh, sqrt
from pathlib import Path
import csv

ROOT = Path(__file__).resolve().parent

x = [1.0, -1.0]
t = [0.2, -0.3, 0.1]
w_hidden = [0.1, -0.2]
w_output = [[0.05, 0.2], [-0.1, -0.15], [0.15, 0.1]]
eta = 1.0
epsilon = 0.001
max_epochs = 10000
history = []

def activation(net):
    return tanh(net / 2.0)

def derivative(output):
    return 0.5 * (1.0 - output ** 2)

for epoch in range(max_epochs + 1):
    net_h = sum(w * value for w, value in zip(w_hidden, x))
    hidden = activation(net_h)
    net_y = [w[0] + w[1] * hidden for w in w_output]
    y = [activation(net) for net in net_y]
    error = sqrt(sum((target - out) ** 2 for target, out in zip(t, y)))
    delta_y = [derivative(out) * (target - out) for target, out in zip(t, y)]
    delta_h = derivative(hidden) * sum(w[1] * d for w, d in zip(w_output, delta_y))
    weights = w_hidden + [value for pair in w_output for value in pair]
    history.append([epoch, *x, *t, net_h, hidden, *net_y, *y, error, *weights, delta_h, *delta_y])
    print(f"k={epoch}; x={x}; t={t}; h={hidden:.8f}; y={y}; E={error:.8f}")
    print(f"w_hidden={w_hidden}; w_y1={w_output[0]}; w_y2={w_output[1]}; w_y3={w_output[2]}")
    if error <= epsilon:
        break
    if epoch == max_epochs:
        raise RuntimeError("Target accuracy was not reached")
    for i in range(len(w_hidden)):
        w_hidden[i] += eta * x[i] * delta_h
    for m in range(len(w_output)):
        w_output[m][0] += eta * delta_y[m]
        w_output[m][1] += eta * hidden * delta_y[m]

header = ["k", "x0", "x1", "t1", "t2", "t3", "net_h", "h"]
header += ["net1", "net2", "net3", "y1", "y2", "y3", "E"]
header += ["a0", "a1", "b1", "v1", "b2", "v2", "b3", "v3"]
header += ["delta_h", "delta1", "delta2", "delta3"]
with (ROOT / "training.csv").open("w", newline="", encoding="utf-8") as file:
    writer = csv.writer(file)
    writer.writerow(header)
    writer.writerows(history)
