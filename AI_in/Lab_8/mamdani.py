from math import fsum

INPUTS = (7, 6, 4)
RULE_CENTERS = ((5, 5, 5), (5, 3, 5), (5, 2, 1))
OUTPUT_TERMS = ((2, 2), (5, 3), (8, 2))


def triangle(value, center, half_width):
    return max(0.0, 1.0 - abs(value - center) / half_width)


def fuzzify(inputs):
    if len(inputs) != 3:
        raise ValueError("Three inputs are required")
    return [[triangle(x, c, 5) for x, c in zip(inputs, centers)]
            for centers in RULE_CENTERS]


def clipped_outputs(y, levels):
    return [min(level, triangle(y, center, width))
            for level, (center, width) in zip(levels, OUTPUT_TERMS)]


def centroid(levels, steps=10000):
    left = min(c - w for c, w in OUTPUT_TERMS)
    right = max(c + w for c, w in OUTPUT_TERMS)
    h = (right - left) / steps
    area_terms, moment_terms = [], []
    for i in range(steps + 1):
        y = left + h * i
        mu = max(clipped_outputs(y, levels))
        weight = 0.5 if i in (0, steps) else 1.0
        area_terms.append(weight * mu)
        moment_terms.append(weight * y * mu)
    area = h * fsum(area_terms)
    moment = h * fsum(moment_terms)
    if area == 0:
        raise ValueError("No active rule; centroid is undefined")
    return area, moment, moment / area


def main():
    degrees = fuzzify(INPUTS)
    levels = [min(row) for row in degrees]
    for j, (row, level) in enumerate(zip(degrees, levels), start=1):
        print(f"Rule {j}: " + ", ".join(f"{v:.1f}" for v in row)
              + f"; level = {level:.1f}")
    area, moment, output = centroid(levels)
    print(f"S = {area:.8f}\nM = {moment:.8f}\ny = {output:.8f}")


if __name__ == "__main__":
    main()
