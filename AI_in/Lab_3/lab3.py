import os
import matplotlib.pyplot as plt
from math import sqrt

N = 20
A = -0.5
B = 0.5

BASE_P = 4
BASE_ETA = 1.0
BASE_M = 4000

M_VALUES = [500, 1000, 2000, 3000, 4000]
ETA_VALUES = [0.1, 0.3, 0.5, 0.7, 1.0]
P_VALUES = [2, 3, 4, 5, 6, 7, 8]

os.makedirs("graphs", exist_ok=True)

def func(t):
    return t ** 4 - 2 * t ** 3 + t

def build_data():
    dt = (B - A) / (N - 1)
    train_t = []
    train_x = []
    for i in range(N):
        t = A + i * dt
        train_t.append(t)
        train_x.append(func(t))
    return train_t, train_x, dt

def train_model(train_x, p, eta, epochs):
    W = [0.0] * (p + 1)
    for epoch in range(epochs):
        for i in range(p, len(train_x)):
            net = W[0]
            for j in range(p):
                net += W[j + 1] * train_x[i - p + j]
            y = net
            error = train_x[i] - y
            for j in range(p):
                W[j + 1] += eta * error * train_x[i - p + j]
    return W

def forecast(train_x, W, p, dt):
    history = train_x.copy()
    forecast_t = []
    forecast_x = []
    for i in range(N):
        net = W[0]
        for j in range(p):
            net += W[j + 1] * history[-p + j]
        y = net
        t = B + (i + 1) * dt
        forecast_x.append(y)
        forecast_t.append(t)
        history.append(func(t))
    return forecast_t, forecast_x

def calculate_error(forecast_t, forecast_x):
    error = 0
    for i in range(len(forecast_x)):
        error += (func(forecast_t[i]) - forecast_x[i]) ** 2
    return sqrt(error)

def run_model(train_x, p, eta, epochs, dt):
    W = train_model(train_x, p, eta, epochs)
    forecast_t, forecast_x = forecast(train_x, W, p, dt)
    error = calculate_error(forecast_t, forecast_x)
    return W, forecast_t, forecast_x, error

def save_forecast(train_t, train_x, forecast_t, forecast_x, title, filename):
    real_t = train_t + forecast_t
    real_x = []
    for t in real_t:
        real_x.append(func(t))
    plt.figure()
    plt.plot(real_t, real_x, label="Real function")
    plt.plot(train_t, train_x, "o", markerfacecolor="none", label="Training data")
    plt.plot(forecast_t, forecast_x, "o", markerfacecolor="none", label="Forecast")
    plt.axvline(B, linestyle="--")
    plt.xlabel("t")
    plt.ylabel("x(t)")
    plt.title(title)
    plt.grid()
    plt.legend()
    plt.savefig("graphs/" + filename, dpi=200, bbox_inches="tight")
    plt.close()

def experiment_epochs(train_t, train_x, dt):
    errors = []
    for epochs in M_VALUES:
        W, forecast_t, forecast_x, error = run_model(train_x, BASE_P, BASE_ETA, epochs, dt)
        errors.append(error)
        print("M =", epochs, "error =", error, "W =", W)
        save_forecast(train_t, train_x, forecast_t, forecast_x, "Short-term forecast, M = " + str(epochs), "forecast_M_" + str(epochs) + ".png")
    plt.figure()
    plt.plot(M_VALUES, errors, marker="o")
    plt.xlabel("M")
    plt.ylabel("Error")
    plt.title("Error dependence on epochs")
    plt.grid()
    plt.savefig("graphs/error_M.png", dpi=200, bbox_inches="tight")
    plt.close()

def experiment_eta(train_x, dt):
    errors = []
    for eta in ETA_VALUES:
        W, forecast_t, forecast_x, error = run_model(train_x, BASE_P, eta, BASE_M, dt)
        errors.append(error)
        print("eta =", eta, "error =", error, "W =", W)
    plt.figure()
    plt.plot(ETA_VALUES, errors, marker="o")
    plt.xlabel("eta")
    plt.ylabel("Error")
    plt.title("Error dependence on learning rate")
    plt.grid()
    plt.savefig("graphs/error_eta.png", dpi=200, bbox_inches="tight")
    plt.close()

def experiment_window(train_t, train_x, dt):
    errors = []
    for p in P_VALUES:
        W, forecast_t, forecast_x, error = run_model(train_x, p, BASE_ETA, BASE_M, dt)
        errors.append(error)
        print("p =", p, "error =", error, "W =", W)
        save_forecast(train_t, train_x, forecast_t, forecast_x, "Short-term forecast, p = " + str(p), "forecast_p_" + str(p) + ".png")
    plt.figure()
    plt.plot(P_VALUES, errors, marker="o")
    plt.xlabel("p")
    plt.ylabel("Error")
    plt.title("Error dependence on window size")
    plt.grid()
    plt.savefig("graphs/error_p.png", dpi=200, bbox_inches="tight")
    plt.close()

train_t, train_x, dt = build_data()

experiment_epochs(train_t, train_x, dt)
experiment_eta(train_x, dt)
experiment_window(train_t, train_x, dt)
