import tkinter as tk

ROWS = 5
COLS = 3
INPUTS = ROWS * COLS
CLASSES = 10

LEARNING_RATE = 0.1
MAX_EPOCHS = 500
TRAIN_MARGIN = 0.5

SCORE_THRESHOLD = 0.9
GAP_THRESHOLD = 0.35
MAX_TEMPLATE_DISTANCE = 3


DIGITS = {
    0: [
        "111",
        "101",
        "101",
        "101",
        "111",
    ],
    1: [
        "010",
        "110",
        "010",
        "010",
        "111",
    ],
    2: [
        "111",
        "001",
        "111",
        "100",
        "111",
    ],
    3: [
        "111",
        "001",
        "111",
        "001",
        "111",
    ],
    4: [
        "101",
        "101",
        "111",
        "001",
        "001",
    ],
    5: [
        "111",
        "100",
        "111",
        "001",
        "111",
    ],
    6: [
        "111",
        "100",
        "111",
        "101",
        "111",
    ],
    7: [
        "111",
        "001",
        "010",
        "010",
        "010",
    ],
    8: [
        "111",
        "101",
        "111",
        "101",
        "111",
    ],
    9: [
        "111",
        "101",
        "111",
        "001",
        "111",
    ],
}


def image_to_vector(image):
    return [int(pixel) for row in image for pixel in row]


def center_image(vector):
    matrix = [
        vector[row * COLS:(row + 1) * COLS]
        for row in range(ROWS)
    ]

    points = [
        (row, col)
        for row in range(ROWS)
        for col in range(COLS)
        if matrix[row][col] == 1
    ]

    if not points:
        return vector[:]

    min_row = min(row for row, _ in points)
    max_row = max(row for row, _ in points)
    min_col = min(col for _, col in points)
    max_col = max(col for _, col in points)

    height = max_row - min_row + 1
    width = max_col - min_col + 1

    target_row = (ROWS - height) // 2
    target_col = (COLS - width) // 2

    result = [[0] * COLS for _ in range(ROWS)]

    for row, col in points:
        new_row = row - min_row + target_row
        new_col = col - min_col + target_col

        if 0 <= new_row < ROWS and 0 <= new_col < COLS:
            result[new_row][new_col] = 1

    return [pixel for row in result for pixel in row]


def hamming_distance(a, b):
    return sum(x != y for x, y in zip(a, b))


X = [image_to_vector(DIGITS[digit]) for digit in range(CLASSES)]
Y = list(range(CLASSES))


class Perceptron:
    def __init__(self):
        self.weights = [[0.0] * INPUTS for _ in range(CLASSES)]
        self.bias = [0.0] * CLASSES

    def scores(self, x):
        result = []

        for digit in range(CLASSES):
            value = self.bias[digit]

            for i in range(INPUTS):
                value += self.weights[digit][i] * x[i]

            result.append(value)

        return result

    def predict(self, x):
        values = self.scores(x)
        return max(range(CLASSES), key=lambda digit: values[digit])

    def train(self, X, Y):
        for epoch in range(MAX_EPOCHS):
            updates = 0

            for x, answer in zip(X, Y):
                values = self.scores(x)

                wrong = max(
                    (digit for digit in range(CLASSES) if digit != answer),
                    key=lambda digit: values[digit]
                )

                if values[answer] <= values[wrong] + TRAIN_MARGIN:
                    for i in range(INPUTS):
                        self.weights[answer][i] += LEARNING_RATE * x[i]
                        self.weights[wrong][i] -= LEARNING_RATE * x[i]

                    self.bias[answer] += LEARNING_RATE
                    self.bias[wrong] -= LEARNING_RATE
                    updates += 1

            print(f"Эпоха {epoch + 1}: корректировок {updates}")

            if updates == 0:
                print("Обучение завершено.\n")
                return

        print("Достигнуто максимальное число эпох.\n")


model = Perceptron()
model.train(X, Y)


print("Проверка на обучающих данных:")

correct = 0

for x, answer in zip(X, Y):
    prediction = model.predict(x)
    print(f"Цифра {answer} -> распознано {prediction}")

    if prediction == answer:
        correct += 1

print(f"Точность: {correct}/{CLASSES}\n")


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Персептрон: цифры 3x5")
        self.root.resizable(False, False)

        self.cells = [0] * INPUTS
        self.buttons = []

        title = tk.Label(
            root,
            text="Нарисуйте цифру 0–9",
            font=("Arial", 16, "bold")
        )
        title.pack(pady=(15, 10))

        grid = tk.Frame(root)
        grid.pack(padx=20, pady=5)

        for row in range(ROWS):
            for col in range(COLS):
                index = row * COLS + col

                button = tk.Button(
                    grid,
                    width=5,
                    height=2,
                    bg="white",
                    activebackground="gray80",
                    command=lambda i=index: self.toggle_cell(i)
                )

                button.grid(row=row, column=col, padx=2, pady=2)
                self.buttons.append(button)

        actions = tk.Frame(root)
        actions.pack(pady=12)

        tk.Button(
            actions,
            text="Распознать",
            width=14,
            command=self.recognize
        ).grid(row=0, column=0, padx=5)

        tk.Button(
            actions,
            text="Очистить",
            width=14,
            command=self.clear
        ).grid(row=0, column=1, padx=5)

        self.result = tk.Label(
            root,
            text="Результат: —",
            font=("Arial", 18, "bold")
        )
        self.result.pack(pady=(5, 5))

        self.info = tk.Label(
            root,
            text="",
            font=("Arial", 10),
            justify="left"
        )
        self.info.pack(padx=15, pady=(0, 15))

    def toggle_cell(self, index):
        self.cells[index] = 1 - self.cells[index]

        if self.cells[index]:
            self.buttons[index].configure(bg="black")
        else:
            self.buttons[index].configure(bg="white")

    def clear(self):
        self.cells = [0] * INPUTS

        for button in self.buttons:
            button.configure(bg="white")

        self.result.configure(text="Результат: —")
        self.info.configure(text="")

    def recognize(self):
        x = center_image(self.cells)

        if sum(x) == 0:
            self.result.configure(text="Результат: не цифра")
            self.info.configure(text="Поле пустое.")
            return

        values = model.scores(x)
        order = sorted(range(CLASSES), key=lambda digit: values[digit], reverse=True)

        best_digit = order[0]
        best_score = values[best_digit]
        second_score = values[order[1]]
        gap = best_score - second_score

        distance = min(hamming_distance(x, template) for template in X)

        is_digit = (
            best_score >= SCORE_THRESHOLD
            and gap >= GAP_THRESHOLD
            and distance <= MAX_TEMPLATE_DISTANCE
        )

        if is_digit:
            self.result.configure(text=f"Результат: {best_digit}")
        else:
            self.result.configure(text="Результат: не цифра")

        scores_text = "  ".join(
            f"{digit}: {values[digit]:.1f}"
            for digit in range(CLASSES)
        )

        self.info.configure(
            text=(
                f"Максимальный выход: {best_score:.2f}\n"
                f"Отрыв от второго: {gap:.2f}\n"
                f"Отклонение от ближайшего эталона: {distance} клеток\n\n"
                f"Выходы персептрона:\n{scores_text}"
            )
        )


root = tk.Tk()
App(root)
root.mainloop()
