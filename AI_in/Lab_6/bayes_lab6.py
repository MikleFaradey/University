from itertools import product
from math import prod
from pathlib import Path
P=(0.7,0.1,0.2)
Q=((0.8,0.1,0.9,0.1),(0.8,0.1,0.8,0.9),(0.1,0.9,0.0,0.6))
FIVE_CASES=((1,1,1,1),(0,1,1,1),(1,0,1,1),(1,1,0,1),(1,1,1,0))
def classify(x):
    if len(x)!=4 or any(v not in (0,1) for v in x): raise ValueError("Требуются четыре бинарных признака")
    w=[P[j]*prod(Q[j][i] if x[i] else 1-Q[j][i] for i in range(4)) for j in range(3)]
    z=sum(w)
    if z<=0: raise ValueError("Нулевая вероятность комплекса признаков")
    r=[v/z for v in w]
    assert abs(sum(r)-1)<1e-12
    return w,z,r
def fmt(v): return f"{v:.5f}".replace(".",",")
def main():
    print("Пять комбинаций признаков:")
    for x in FIVE_CASES:
        w,z,r=classify(x)
        k=max(range(3),key=lambda j:r[j])+1
        print("".join(map(str,x)),"веса:",[round(v,8) for v in w],"P(S):",round(z,8),"вероятности:",[round(v,8) for v in r],"класс:",f"D{k}")
    rows=[]
    for x in product((0,1),repeat=4):
        _,_,r=classify(x)
        k=max(range(3),key=lambda j:r[j])+1
        rows.append(" & ".join([*map(str,x),*(fmt(v) for v in r),f"$D_{k}$"])+r" \\ \hline")
    target=Path(__file__).with_name("all_cases.tex")
    target.write_text("\n".join(rows)+"\n",encoding="utf-8")
    print(f"Создана таблица для отчета: {target.name} ({len(rows)} строк)")
if __name__=="__main__": main()
