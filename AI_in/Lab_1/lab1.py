import argparse
import matplotlib.pyplot as plt
from math import exp
from itertools import product, combinations

TETTA = 0.3
MAX_EPOCH = 5000
X = []
F = []

def bull(x1, x2, x3, x4):
    return ((not x3) or x4) and (not x1) or x2

def build_table():
    X.clear()
    F.clear()
    for x1, x2, x3, x4 in product([0, 1], repeat=4):
        X.append([1, x1, x2, x3, x4])
        F.append(int(bull(x1, x2, x3, x4)))

def func(net, number):
    if number == 1:
        return 1 if net >= 0 else 0
    elif number == 3:
        return 1 / (1 + exp(-net))
    else:
        raise ValueError("Invalid function number")

def func_diff(net, number):
    if number == 3:
        y = func(net, number)
        return y * (1 - y)
    return 1

def calculate_net(W, x):
    net = 0
    for i in range(len(W)):
        net += W[i] * x[i]
    return net

def to_class(y, function_number):
    if function_number == 1:
        return y
    return 1 if y >= 0.5 else 0

def teach_model(function_number, train_indexes, verbose=False):
    W = [0.0, 0.0, 0.0, 0.0, 0.0]
    error_points = []
    for epoch in range(MAX_EPOCH):
        epoch_error = 0
        for index in train_indexes:
            x = X[index]
            target = F[index]
            net = calculate_net(W, x)
            y = func(net, function_number)
            error = target - y
            epoch_error += error ** 2
            if function_number == 1:
                for j in range(len(W)):
                    W[j] += TETTA * error * x[j]
            elif function_number == 3:
                y_diff = func_diff(net, function_number)
                for j in range(len(W)):
                    W[j] += TETTA * error * y_diff * x[j]
        error_points.append(epoch_error)
        if verbose:
            print("epoch =", epoch, "W =", W, "E =", epoch_error)
        if function_number == 1 and epoch_error == 0:
            break
        if function_number == 3 and epoch_error < 0.01:
            break
    return W, error_points, epoch + 1

def test_model(function_number, W, verbose=False):
    result = True
    for i in range(len(X)):
        net = calculate_net(W, X[i])
        y = func(net, function_number)
        prediction = to_class(y, function_number)
        if verbose:
            print(X[i][1:], "target =", F[i], "output =", y, "class =", prediction)
        if prediction != F[i]:
            result = False
    return result

def full_training(function_number):
    indexes = range(len(X))
    W, error_points, epochs = teach_model(function_number, indexes, True)
    print()
    print("Epochs:", epochs)
    print("W:", W)
    print("E:", error_points[-1])
    print()
    print("Test:")
    result = test_model(function_number, W, True)
    print()
    print("Result:", result)
    plt.figure()
    plt.plot(range(1, len(error_points) + 1), error_points, marker="o", markerfacecolor="none", markersize=4, linewidth=1)
    plt.xlabel("k")
    plt.ylabel("E(k)")
    plt.grid()
    plt.show()

def test_with_less_data(function_number):
    for taken in range(1, len(X) + 1):
        print()
        print("Testing length:", taken)
        comb = combinations(range(len(X)), taken)
        checked = 0
        for indexes in comb:
            checked += 1
            W, error_points, epochs = teach_model(function_number, indexes)
            if test_model(function_number, W):
                print()
                print("Minimum length:", taken)
                print("Epochs:", epochs)
                print("Checked combinations:", checked)
                print("Indexes:", indexes)
                print("W:", W)
                print("Training error:", error_points[-1])
                print()
                print("Training vectors:")
                for index in indexes:
                    print(X[index][1:], "->", F[index])
                print()
                print("Test on all 16 vectors:")
                test_model(function_number, W, True)
                return
        print("No suitable combinations with length", taken)
    print("No suitable combination found")

def print_truth_table():
    print("x1 x2 x3 x4 | F")
    for i in range(len(X)):
        print(X[i][1], X[i][2], X[i][3], X[i][4], "|", F[i])

parser = argparse.ArgumentParser()
parser.add_argument("-f", "--func", type=int, choices=[1, 3], required=True, help="Activation function: 1 or 3")
parser.add_argument("-m", "--mode", choices=["train", "min"], required=True, help="train - full training, min - minimum training set")
args = parser.parse_args()

build_table()
print_truth_table()

if args.mode == "train":
    full_training(args.func)
elif args.mode == "min":
    test_with_less_data(args.func)
