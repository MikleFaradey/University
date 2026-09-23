import numpy as np
import matplotlib.pyplot as plt


def f(x1, x2):
    return (x1**3 - x2)**2 + x2**2


def polynomial(y):
    return 9*y**5 - 9*y**4 + 4*y**3 - 12*y**2 + 13*y - 4


roots = np.roots([9, -9, 4, -12, 13, -4])
y = [r.real for r in roots if abs(r.imag) < 1e-9 and 0 < r.real < 1][0]
x1_b = np.sqrt(y)
x2_b = x1_b * (3 - 4*y) / (3*y**2 - 2)
lambda1_b = 3*x1_b*x2_b - 3*x1_b**4

points = {
    "A": (0.0, 0.0),
    "B": (x1_b, x2_b),
    "C": (0.0, 1.0),
    "D": (0.0, -1.0),
}

print("Условно-стационарные точки:")
for name, (x1, x2) in points.items():
    print(f"{name}: x1={x1:.9f}, x2={x2:.9f}, f={f(x1, x2):.9f}")

print(f"lambda_1(B) = {lambda1_b:.9f}")
print("lambda_1(C) = lambda_1(D) = -2")

# Графическое представление области допустимых решений и линий уровня функции.
x1 = np.linspace(0, 1, 500)
x2 = np.linspace(-1, 1, 500)
X1, X2 = np.meshgrid(x1, x2)
Z = f(X1, X2)
mask = X1**2 + X2**2 <= 1
Z = np.where(mask, Z, np.nan)

plt.figure(figsize=(8, 6))
cs = plt.contourf(X1, X2, Z, levels=30)
plt.colorbar(cs, label=r"$f(x_1,x_2)$")

t = np.linspace(-np.pi/2, np.pi/2, 400)
plt.plot(np.cos(t), np.sin(t), linewidth=1.5)
plt.plot([0, 0], [-1, 1], linewidth=1.5)

for name, (px, py) in points.items():
    plt.scatter(px, py)
    plt.annotate(name, (px, py), xytext=(6, 6), textcoords="offset points")

plt.xlabel(r"$x_1$")
plt.ylabel(r"$x_2$")
plt.title("Допустимая область и условно-стационарные точки")
plt.axis("equal")
plt.grid(True)
plt.tight_layout()
plt.savefig("result_2_2.png", dpi=200)
plt.close()
