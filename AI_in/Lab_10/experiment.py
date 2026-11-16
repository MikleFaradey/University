"""RBF approximation, variant 2. Run with Python 3, numpy and matplotlib."""
import csv
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
A, B = -0.5, 0.5
Q, J, K = 20, 9, 50
CENTERS = A + np.arange(1, J + 1) * (B - A) / (J + 1)
TRAIN = np.linspace(A, B, Q)
CHECK = np.linspace(A, B, 401)
ETAS = np.arange(5, 26) / 100
WIDTHS = (0.05, 0.1, 0.15, 0.2, 0.3, 0.5)


def target(t):
    return t**4 - 2*t**3 + t


def basis(t, sigma):
    return np.exp(-0.5 * ((t[:, None] - CENTERS) / sigma)**2)


def train(sigma, eta, record=False):
    phi = basis(TRAIN, sigma)
    weights = np.zeros(J)
    goals = target(TRAIN)
    history = [np.linalg.norm(goals)]
    steps = []
    for epoch in range(1, K + 1):
        for i, row in enumerate(phi):
            output = row @ weights
            delta = goals[i] - output
            weights += eta * delta * row
            if record:
                steps.append((epoch, i+1, TRAIN[i], goals[i], output,
                              delta, *weights))
        history.append(np.linalg.norm(goals - phi @ weights))
    return weights, history, steps


def save_csv(name, columns, rows):
    with (ROOT / 'results' / name).open('w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)


def main():
    (ROOT / 'results').mkdir(exist_ok=True)
    (ROOT / 'inc').mkdir(exist_ok=True)
    errors = np.empty((len(WIDTHS), len(ETAS)))
    summary = []
    for i, sigma in enumerate(WIDTHS):
        for j, eta in enumerate(ETAS):
            weights, history, _ = train(sigma, eta)
            errors[i, j] = history[-1]
            residual = target(CHECK) - basis(CHECK, sigma) @ weights
            summary.append((sigma, eta, history[-1],
                            np.sqrt(np.mean(residual**2))))
    i, j = np.unravel_index(np.argmin(errors), errors.shape)
    sigma, eta = WIDTHS[i], ETAS[j]
    weights, history, steps = train(sigma, eta, True)
    names = [f'v{k}' for k in range(1, J+1)]
    save_csv('steps.csv', ['epoch','sample','t','target','y_before',
                          'delta',*names], steps)
    save_csv('epochs.csv', ['epoch','E'], enumerate(history))
    save_csv('search.csv', ['sigma','eta','E_train','RMSE_check'], summary)
    prediction = basis(CHECK, sigma) @ weights
    fig, ax = plt.subplots(figsize=(7, 3.2))
    ax.plot(CHECK, target(CHECK), color='black', label='Заданная функция')
    ax.plot(CHECK, prediction, '--', label='Выход сети')
    ax.scatter(TRAIN,target(TRAIN),facecolors='none',edgecolors='#943d17',
               label='Обучающие точки')
    ax.set(xlabel='Аргумент t', ylabel='Значение функции')
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(ROOT/'inc'/'fit.png', dpi=190)
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.4))
    for rate in (0.05, 0.2, eta):
        axes[0].semilogy(range(K+1), train(sigma,rate)[1],
                         label=f'η = {rate:g}')
    for width, values in zip(WIDTHS, errors):
        axes[1].semilogy(ETAS, values, label=f'σ = {width:g}')
    axes[0].set(xlabel='Эпоха',ylabel='Ошибка E')
    axes[1].set(xlabel='Норма обучения η',ylabel='Ошибка после 50 эпох')
    for ax in axes:
        ax.grid(alpha=.25)
        ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(ROOT/'inc'/'errors.png', dpi=190)
    plt.close(fig)
    print('sigma, eta, E:', sigma, eta, history[-1])
    print('weights:', weights)
    print('max error:', np.max(abs(prediction-target(CHECK))))


if __name__ == '__main__':
    main()
