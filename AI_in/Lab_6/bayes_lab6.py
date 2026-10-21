"""Лабораторная работа № 6, вариант 2: наивный байесовский классификатор.

Стандартная библиотека Python; при запуске формирует all_cases.tex для отчёта.
"""

from itertools import product
from math import prod
from pathlib import Path

PRIORS = (0.7, 0.1, 0.2)
CONDITIONAL = (
    (0.8, 0.1, 0.9, 0.1),  # D1
    (0.8, 0.1, 0.8, 0.9),  # D2
    (0.1, 0.9, 0.0, 0.6),  # D3
)

# Порядок пяти ситуаций соответствует слайду 26 лекции.
FIVE_CASES = (
    (1, 1, 1, 1),
    (0, 1, 1, 1),
    (1, 0, 1, 1),
    (1, 1, 0, 1),
    (1, 1, 1, 0),
)


def classify(observation):
    """Вернуть ненормированные веса, P(S) и апостериорные вероятности."""
    if len(observation) != 4 or any(x not in (0, 1) for x in observation):
        raise ValueError("Нужен набор из четырех бинарных признаков")
    weights = [
        PRIORS[j] * prod(
            CONDITIONAL[j][i] if observation[i] else 1 - CONDITIONAL[j][i]
            for i in range(4)
        )
        for j in range(3)
    ]
    evidence = sum(weights)
    if evidence <= 0:
        raise ValueError("Нормирующая вероятность равна нулю")
    probabilities = [weight / evidence for weight in weights]
    assert abs(sum(probabilities) - 1.0) < 1e-12
    return weights, evidence, probabilities


def fmt(value):
    return f"{value:.5f}".replace(".", ",")


def main():
    print("Пять комбинаций, использованных в отчете:")
    for observation in FIVE_CASES:
        weights, evidence, probabilities = classify(observation)
        winner = max(range(3), key=lambda j: probabilities[j]) + 1
        print(
            "".join(map(str, observation)),
            "веса:", [round(w, 8) for w in weights],
            "P(S):", round(evidence, 8),
            "апостериорные:", [round(p, 8) for p in probabilities],
            "класс:", f"D{winner}",
        )

    table_rows = []
    for observation in product((0, 1), repeat=4):
        _, _, probabilities = classify(observation)
        winner = max(range(3), key=lambda j: probabilities[j]) + 1
        cells = [str(x) for x in observation]
        cells += [fmt(p) for p in probabilities]
        cells += [f"$D_{winner}$"]
        table_rows.append(" & ".join(cells) + r" \\ \hline")

    output = Path(__file__).with_name("all_cases.tex")
    output.write_text("\n".join(table_rows) + "\n", encoding="utf-8")
    print(f"Создана таблица для отчета: {output.name} ({len(table_rows)} строк)")


if __name__ == "__main__":
    main()
