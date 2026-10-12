import argparse
import ast
import csv
import itertools
import math
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.widgets import CheckButtons
from mpl_toolkits.mplot3d import Axes3D
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from scipy.optimize import linprog
from scipy.spatial import ConvexHull, QhullError


BASIS = np.array([
    [1.0, 0.0, 0.0],
    [0.0, 1.0, 0.0],
    [0.0, 0.0, 1.0],
    [-0.4, math.sqrt(0.03), 0.9],
], dtype=float)

EXAMPLE_FUNCTION = '(((not x3) or x4) and (not x1)) or x2'
ETA = 0.3
MAX_EPOCHS = 5000
W0_INITIAL = -0.05

COLORS = {
    'Перцептрон': '#23a066',
    'Фишер': '#df9e24',
    'Симплекс': '#9a4ce0',
}
COLOR_ZERO = '#257eb8'
COLOR_ONE = '#e96c31'
COLOR_BOUNDARY = '#d83343'
EPS = 1e-9


def normalize_expression(expression):
    return (expression.strip().replace('¬', ' not ')
            .replace('∧', ' and ').replace('∨', ' or ')
            .replace('⊕', ' ^ ').strip())


def evaluate_node(node, env):
    if isinstance(node, ast.Expression):
        return evaluate_node(node.body, env)
    if isinstance(node, ast.Name) and node.id in env:
        return bool(env[node.id])
    if isinstance(node, ast.Constant) and type(node.value) in (bool, int):
        if node.value in (0, 1):
            return bool(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.Not, ast.Invert)):
        return not evaluate_node(node.operand, env)
    if isinstance(node, ast.BoolOp):
        vals = [evaluate_node(v, env) for v in node.values]
        if isinstance(node.op, ast.And):
            return all(vals)
        if isinstance(node.op, ast.Or):
            return any(vals)
    if isinstance(node, ast.BinOp):
        a = evaluate_node(node.left, env)
        b = evaluate_node(node.right, env)
        if isinstance(node.op, ast.BitAnd):
            return a and b
        if isinstance(node.op, ast.BitOr):
            return a or b
        if isinstance(node.op, ast.BitXor):
            return a != b
    raise ValueError('Разрешены только x1..x4, 0/1, not/and/or, ~, &, |, ^ и скобки')


def function_labels(expression, X):
    tree = ast.parse(normalize_expression(expression), mode='eval')
    labels = []
    for bits in X:
        env = {'x%d' % (k + 1): int(bits[k]) for k in range(4)}
        labels.append(int(evaluate_node(tree, env)))
    return np.asarray(labels, dtype=int)


def build_cube():
    X = np.array(list(itertools.product((0, 1), repeat=4)), dtype=int)
    edges = [(i, j) for i in range(16) for j in range(i + 1, 16)
             if np.count_nonzero(X[i] != X[j]) == 1]
    assert X.shape == (16, 4) and len(edges) == 32
    assert np.allclose(np.linalg.norm(BASIS, axis=1), 1.0)
    assert len(np.unique(np.round(X @ BASIS, 9), axis=0)) == 16
    return X, edges


def boundary_edges(edges, y):
    return [(i, j) for i, j in edges if y[i] != y[j]]


def augmented(X):
    return np.column_stack((np.asarray(X, dtype=float), np.ones(len(X))))


def linear_separability(X, y):
    t = 2 * y - 1
    A = augmented(X)
    kw = dict(c=np.zeros(5), A_ub=-(t[:, None] * A),
              b_ub=-np.ones(len(X)), bounds=[(None, None)] * 5)
    try:
        r = linprog(method='highs', **kw)
    except ValueError:
        r = linprog(method='interior-point', **kw)
    if r.status == 2:
        return False, None
    if not r.success:
        raise RuntimeError('Проверка разделимости: ' + str(r.message))
    if np.min(t * (A @ r.x)) < 1 - 1e-6:
        raise RuntimeError('Нарушены ограничения LP из-за численной ошибки')
    return True, np.asarray(r.x, dtype=float)


def predict_threshold(X, theta):
    return (augmented(X) @ theta >= 0).astype(int)


def train_perceptron(X, y, eta=ETA, max_epochs=MAX_EPOCHS):


    w = np.array([0., 0., 0., 0., W0_INITIAL])
    A = augmented(X)
    history = []
    for epoch in range(1, max_epochs + 1):
        updates = 0
        for row, expected in zip(A, y):
            actual = int(np.dot(w, row) >= 0)
            delta = int(expected) - actual
            if delta:
                w += eta * delta * row
                updates += 1
        mistakes = int(np.count_nonzero(predict_threshold(X, w) != y))
        history.append((epoch, updates, mistakes))
        if mistakes == 0:
            return w, history, True
    return w, history, False


def train_fisher(X, y):
    c0 = X[y == 0].astype(float)
    c1 = X[y == 1].astype(float)
    m0, m1 = c0.mean(axis=0), c1.mean(axis=0)
    d0, d1 = c0 - m0, c1 - m1
    S0, S1 = d0.T @ d0, d1.T @ d1
    SW = S0 + S1
    det = float(np.linalg.det(SW))
    inverse = np.linalg.inv(SW) if abs(det) > 1e-10 else np.linalg.pinv(SW)
    raw = inverse @ (m1 - m0)
    norm = float(np.linalg.norm(raw))
    if norm <= 1e-12:
        raise ValueError('Направление Фишера не определено')
    w = raw / norm
    z = X @ w
    z0, z1 = z[y == 0], z[y == 1]
    threshold = float((z0.max() + z1.min()) / 2)
    means = (float(z0.mean()), float(z1.mean()))
    variances = (float(np.sum((z0 - means[0])**2)), float(np.sum((z1 - means[1])**2)))
    J = (means[1]-means[0])**2/sum(variances)
    details = dict(m0=m0,m1=m1,S0=S0,S1=S1,SW=SW,inverse=inverse,
                   raw=raw, w=w, projected=z, z0=z0, z1=z1,
                   projmeans=means, variances=variances, between=(means[1]-means[0])**2,
                   within=sum(variances),J=J,threshold=threshold,det=det,
                   overlap=bool(z0.max() >= z1.min()))
    return np.r_[w,-threshold],details


def fisher_criterion(theta, SW, delta):
    w = theta[:4]
    num = float((w @ delta)**2)
    den = float(w @ SW @ w)
    if den <= 1e-14:
        return float('nan') if num <= 1e-14 else float('inf')
    return num/den


def train_simplex(X, y, boundary):
    boundary_indices = sorted({k for edge in boundary for k in edge})
    candidate = np.mean(X[y == 1],axis=0) - np.mean(X[y == 0],axis=0)
    preferred = tuple(int(v < 0) for v in candidate)
    flips = [preferred] + [x for x in itertools.product([0,1],repeat=4) if x != preferred]
    for flip in flips:
        mask = np.asarray(flip,dtype=bool)
        Xt = X.astype(float).copy()
        Xt[:,mask] = 1-Xt[:,mask]
        rows = np.array([np.r_[Xt[i] if y[i] == 0 else -Xt[i], 1]
                         for i in boundary_indices])
        rhs = np.array([1. if y[i] == 0 else -1. for i in boundary_indices])
        result = linprog([0,0,0,0,-1],A_ub=rows,b_ub=rhs,
                         bounds=[(0,None)]*5,method='highs-ds')
        if not result.success:
            continue
        a = result.x[:4]
        lam = float(result.x[4])
        w = np.where(mask,-a,a)
        b = float(sum(a[mask])-1)
        scores = X@w+b
        signed = (2*y-1)*scores
        if lam < -1e-7 or np.min(signed) < -1e-7:
            continue
        details = dict(flip=mask,XT=Xt, a=a,lam=lam,solution=result.x,
                       boundary_indices=boundary_indices,rows=rows,rhs=rhs,
                       constraints_count=len(boundary_indices),
                       all_constraints_ok=bool(np.min(signed)>=-1e-7))
        return np.r_[w,b],details
    raise ValueError('Не удалось решить задачу симплекс-методом после преобразования координат')


def unit_signed_margin(theta, X, y):
    normal = np.linalg.norm(theta[:4])
    if normal < 1e-12:
        return float('nan')
    return float(np.min((2*y - 1) * (augmented(X) @ theta) / normal))


def oriented_angle_degrees(a, b):
    x, z = a[:4], b[:4]
    val = float(np.dot(x, z) / (np.linalg.norm(x)*np.linalg.norm(z)))
    return float(np.degrees(np.arccos(np.clip(val, -1.0, 1.0))))


def boundary_intersections(X, edges, y, theta):
    scores = augmented(X) @ theta
    result = {}
    for i, j in edges:
        if y[i] == y[j]:
            continue
        z, o = (i, j) if y[i] == 0 else (j, i)
        g0, g1 = scores[z], scores[o]
        if abs(g1 - g0) <= 1e-12:
            frac = 0.0 if abs(g0) <= 1e-12 else None
        else:
            frac = float(-g0/(g1-g0))
            if frac < -1e-7 or frac > 1+1e-7:
                frac = None
            elif frac is not None:
                frac = float(np.clip(frac, 0, 1))
        result[(i,j)] = frac
    return result


def section_vertices(X, edges, theta):
    values = augmented(X) @ theta
    points = []
    for i, j in edges:
        a, b = float(values[i]), float(values[j])
        if abs(a) <= EPS:
            points.append(X[i].astype(float))
        if abs(b) <= EPS:
            points.append(X[j].astype(float))
        if a*b < 0:
            frac = -a/(b-a)
            points.append(X[i] + frac * (X[j] - X[i]))
    if not points:
        return np.empty((0,4), dtype=float)
    values = np.array(points)
    _, indices = np.unique(np.round(values, 9), axis=0, return_index=True)
    return values[np.sort(indices)]


def make_section_artists(ax, X, edges, theta, color):


    points4 = section_vertices(X, edges, theta)
    if len(points4) == 0:
        return [], points4
    Q = points4 @ BASIS
    artists = []
    centered = Q - Q.mean(axis=0)
    singular_values = np.linalg.svd(centered, compute_uv=False)
    rank = int(np.sum(singular_values > 1e-8))
    if rank == 3 and len(Q) >= 4:
        try:
            faces = [Q[tri] for tri in ConvexHull(Q).simplices]
            surface = Poly3DCollection(faces, facecolor=color, edgecolor=color,
                                       alpha=0.13, linewidths=0.65)
            ax.add_collection3d(surface)
            artists.append(surface)
        except QhullError:
            pass
    elif rank == 2 and len(Q) >= 3:
        _, _, vh = np.linalg.svd(centered, full_matrices=False)
        hull2 = ConvexHull(centered @ vh[:2].T)
        poly = Poly3DCollection([Q[hull2.vertices]], facecolor=color,
                                edgecolor=color, alpha=0.28)
        ax.add_collection3d(poly)
        artists.append(poly)
    elif rank == 1 and len(Q) >= 2:
        d = np.linalg.svd(centered, full_matrices=False)[2][0]
        ordered = Q[np.argsort(centered @ d)]
        artists += ax.plot(ordered[[0,-1], 0], ordered[[0,-1], 1],
                           ordered[[0,-1], 2], color=color, linewidth=3)
    cloud = ax.scatter(Q[:,0], Q[:,1], Q[:,2], s=32, c=color,
                       marker='x', linewidths=1.7, depthshade=False)
    artists.append(cloud)
    return artists, points4


def format_eq(theta):
    return ' '.join('%+.6f*x%d' % (theta[i], i+1) for i in range(4)) + ' %+.6f = 0' % theta[4]


def show_table(X, y):
    print('\nТАБЛИЦА ИСТИННОСТИ (все 16 вершин)')
    print_grid(['x1', 'x2', 'x3', 'x4', 'f'],
               [list(map(int, bits)) + [int(v)] for bits, v in zip(X, y)])


def save_table(path, X, y):
    np.savetxt(str(path), np.column_stack((X,y)), delimiter=',', fmt='%d',
               header='x1,x2,x3,x4,f', comments='', encoding='utf-8')


def print_grid(headers, rows, alignments=None):
    rows = [[str(v) for v in row] for row in rows]
    headers = [str(h) for h in headers]
    widths = [max(len(headers[j]), *(len(row[j]) for row in rows)) + 2
              for j in range(len(headers))]
    horizontal = '+' + '+'.join('-' * w for w in widths) + '+'

    def format_row(row):
        return '|' + '|'.join(' ' + cell.ljust(widths[j] - 1)
                            for j, cell in enumerate(row)) + '|'

    print(horizontal)
    print(format_row(headers))
    print(horizontal)
    for row in rows:
        print(format_row(row))
    print(horizontal)


def print_models(X, y, edges, models, stats, boundary):
    print('\nСРАВНЕНИЕ МЕТОДОВ (16 вершин)')
    print_grid(['Метод','Верно','Ошибки','Мин. зазор','Критерий J','Гран. рёбра'],
               [[name,'%d/16'%v['correct'],v['errors'],'%.5f'%v['margin'],
                 '%.6f'%v['J'],'%d/%d'%(v['boundary_cross'],len(boundary))]
                for name,v in stats.items()])
    print('\nКОЭФФИЦИЕНТЫ ГИПЕРПЛОСКОСТЕЙ')
    print_grid(['Метод','w1','w2','w3','w4','b'],
               [[name]+['%.6f'%v for v in theta] for name,theta in models.items()])
    print('\nУРАВНЕНИЯ')
    for name,theta in models.items():
        print('%-12s %s'%(name,format_eq(theta)))
    print('\nУГЛЫ ОТНОСИТЕЛЬНО ФИШЕРА')
    print_grid(['Метод','Угол, °'],
               [[name,'%.4f'%oriented_angle_degrees(theta,models['Фишер'])]
                for name,theta in models.items()])
    print('\nПЕРЕСЕЧЕНИЯ ГРАНИЧНЫХ РЁБЕР (от класса 0 к классу 1)')
    fracs={name:boundary_intersections(X,edges,y,theta) for name,theta in models.items()}
    rows=[]
    for i,j in boundary:
        edge='%s — %s'%(''.join(map(str,X[i])),''.join(map(str,X[j])))
        rows.append([edge]+['%.6f'%fracs[name][(i,j)] if fracs[name][(i,j)] is not None else 'нет'
                            for name in models])
    print_grid(['Ребро']+list(models),rows)


def print_fisher_details(d):
    print('\nФИШЕР: ЦЕНТРОИДЫ')
    print_grid(['Класс','x1','x2','x3','x4'],
               [[label]+['%.6f'%v for v in d['m'+label]] for label in ('0','1')])
    for key in ('S0','S1','SW','inverse'):
        print('\n'+key)
        print_grid(['']+['x%d'%j for j in range(1,5)],
                   [['x%d'%(i+1)]+['%.6f'%v for v in row]
                    for i,row in enumerate(d[key])])
    print('\nФИШЕР: ПРОЕКЦИИ')
    print_grid(['Класс','Точки проекции'],
               [[str(c),' '.join('%.5f'%v for v in d['z'+str(c)])] for c in (0,1)])
    print_grid(['Показатель','Значение'],[
        ['||w||','%.6f'%np.linalg.norm(d['w'])],
        ['Средняя проекция 0','%.6f'%d['projmeans'][0]],
        ['Средняя проекция 1','%.6f'%d['projmeans'][1]],
        ['Разброс между классами','%.6f'%d['between']],
        ['Разброс внутри класса 0','%.6f'%d['variances'][0]],
        ['Разброс внутри класса 1','%.6f'%d['variances'][1]],
        ['Суммарный разброс','%.6f'%d['within']],
        ['Критерий J','%.6f'%d['J']],
        ['Порог крайних проекций','%.6f'%d['threshold']]])


def print_simplex_details(d):
    print('\nСИМПЛЕКС: ПРЕОБРАЗОВАНИЕ КООРДИНАТ')
    print_grid(['Координата','Преобразование','lambda_j'],[
        ['x%d'%(i+1),'1 - x%d'%(i+1) if d['flip'][i] else 'x%d'%(i+1),
         '%.6f'%d['a'][i]] for i in range(4)])
    print_grid(['Показатель','Значение'],[
        ['Нормировка порога','1'],['Максимальный алгебраический отступ','%.6f'%d['lam']],
        ['Граничных вершин в ограничениях',str(d['constraints_count'])]])


def save_projection(path, d):
    fig,ax=plt.subplots(figsize=(10,3.7))
    zz=d['projected']
    for c,col in ((0,COLOR_ZERO),(1,COLOR_ONE)):
        inds=np.where(d['labels']==c)[0]
        ax.scatter(zz[inds],np.full(len(inds),c),s=65,color=col,
                   edgecolor='white',linewidth=0.5,label='Класс '+str(c))
        for i in inds:
            ax.annotate(''.join(map(str,d['X'][i])),(zz[i],c),xytext=(0,9),
                        textcoords='offset points',ha='center',fontsize=7)
    ax.axvline(d['threshold'],ls='--',lw=1.8,color='#d18c19',label='Порог Фишера')
    ax.set_xlabel('Проекция wᵀx')
    ax.set_yticks([0,1]);ax.set_ylim(-0.33,1.42)
    ax.grid(axis='x',alpha=0.2)
    ax.legend(loc='lower right',ncol=3,fontsize=8)
    fig.tight_layout()
    fig.savefig(str(path),dpi=180)
    plt.close(fig)


def save_stats(path, stats):
    with open(str(path), 'w', encoding='utf-8-sig', newline='') as fp:
        writer = csv.writer(fp, delimiter=';')
        writer.writerow(['method', 'correct_of_16', 'errors', 'accuracy_pct',
                         'signed_min_margin', 'fisher_J', 'boundary_edges_crossed',
                         'boundary_edges_total', 'epochs', 'w1', 'w2', 'w3', 'w4', 'b'])
        for name, s in stats.items():
            writer.writerow([name, s['correct'], s['errors'],
                             100*s['correct']/16, s['margin'], s['J'],
                             s['boundary_cross'], s['boundary_total'], s['epochs'],
                             *s['weights']])


def show_hypercube(X, y, edges, boundary, models, stats, expression, image_path, show=True, view='perceptron'):
    P = X @ BASIS
    fig = plt.figure(figsize=(16, 9.8))
    ax = fig.add_axes([0.025, 0.075, 0.71, 0.855], projection='3d')
    ax.set_axis_off()
    if hasattr(ax, 'set_proj_type'):
        ax.set_proj_type('ortho')

    bound_set = set(boundary)
    for i, j in edges:
        pts = P[[i, j]]
        bnd = (i, j) in bound_set
        along_fourth = X[i, 3] != X[j, 3]
        ax.plot(pts[:, 0], pts[:, 1], pts[:, 2],
                color=COLOR_BOUNDARY if bnd else '#858e99',
                linewidth=2.65 if bnd else 1.05,
                linestyle='--' if along_fourth else '-',
                alpha=0.92 if bnd else 0.62)

    plane_artists = {}
    state = {name: view == 'all' or (view == 'fisher' and name == 'Фишер') or (view == 'simplex' and name == 'Симплекс') or (view == 'perceptron' and name == 'Перцептрон') for name in models}
    for name, theta in models.items():
        objs, _ = make_section_artists(ax, X, edges, theta, COLORS[name])
        plane_artists[name] = objs
        for artist in objs:
            artist.set_visible(state[name])

    for k, direction in enumerate(BASIS):
        tip = direction * 1.48
        ax.quiver(0, 0, 0, *tip, color='#20242a',
                  arrow_length_ratio=0.085, linewidth=2.1)
        ax.text(*(direction * 1.70), 'x%d' % (k + 1), fontsize=13.5,
                weight='bold', color='#20242a')

    for xyz, bits, label in zip(P, X, y):
        ax.scatter(*xyz, color=COLOR_ONE if label else COLOR_ZERO,
                   s=81, edgecolors='white', linewidths=0.8,
                   depthshade=False)
        text = '(' + ','.join(map(str, bits)) + ')'
        ax.text(*(xyz + np.array([0.025, 0.03, 0.025])),
                text, fontsize=8.3, color='#20242a')

    ax.view_init(elev=22, azim=38)
    visible = np.vstack((P, BASIS * 1.78, np.zeros((1, 3))))
    middle = 0.5 * (visible.max(axis=0) + visible.min(axis=0))
    radius = 0.55 * np.max(visible.max(axis=0) - visible.min(axis=0))
    ax.set_xlim(middle[0] - radius, middle[0] + radius)
    ax.set_ylim(middle[1] - radius, middle[1] + radius)
    ax.set_zlim(middle[2] - radius, middle[2] + radius)
    if hasattr(ax, 'set_box_aspect'):
        try:
            ax.set_box_aspect((1, 1, 1), zoom=1.15)
        except TypeError:
            ax.set_box_aspect((1, 1, 1))

    fig.suptitle('4D-гиперкуб: перцептрон, Фишер, симплекс-метод', y=0.978,
                 fontsize=15)
    fig.text(0.035, 0.926,
             'Граничные рёбра выделены красным; координаты вершин — (x1,x2,x3,x4)',
             fontsize=10)
    legend = [
        Line2D([0], [0], marker='o', markersize=9, markerfacecolor=COLOR_ZERO,
               markeredgecolor='white', color='none', label='Класс f=0'),
        Line2D([0], [0], marker='o', markersize=9, markerfacecolor=COLOR_ONE,
               markeredgecolor='white', color='none', label='Класс f=1'),
        Line2D([0], [0], color=COLOR_BOUNDARY, linewidth=2.5,
               label='Граничное ребро'),
    ]
    fig.legend(handles=legend, loc='upper left', bbox_to_anchor=(0.035, 0.895),
               fontsize=9)

    names = list(models)
    if names:
        widget_ax = fig.add_axes([0.763, 0.72, 0.22, 0.182])
        widget_ax.set_title('Показывать:', loc='left', fontsize=11)
        labels = names
        checks = CheckButtons(widget_ax, labels, [state[n] for n in labels])
        for label in checks.labels:
            label.set_fontsize(10)

        def toggle(name):
            state[name] = not state[name]
            if name in plane_artists:
                for artist in plane_artists[name]:
                    artist.set_visible(state[name])
            fig.canvas.draw_idle()

        checks.on_clicked(toggle)
        fig._toggle_reference = checks

        fig.text(0.767, 0.683, 'Гиперплоскости', fontsize=10, weight='bold')
        for pos, name in enumerate(names):
            fig.text(0.772, 0.654 - pos * 0.033, '●  ' + name,
                     fontsize=10, color=COLORS[name])

        fig.text(0.767, 0.535, 'Сравнение на 16 вершинах',
                 fontsize=11, weight='bold')
        table_ax = fig.add_axes([0.755, 0.24, 0.238, 0.277])
        table_ax.set_axis_off()
        rows = [
            ['Верно'] + ['%d/16' % stats[n]['correct'] for n in names],
            ['Ошибки'] + [str(stats[n]['errors']) for n in names],
            ['Зазор'] + ['%.4f' % stats[n]['margin'] for n in names],
            ['Фишер J'] + ['%.4f' % stats[n]['J'] for n in names],
            ['Гран. рёбра'] + [
                '%d/%d' % (stats[n]['boundary_cross'], stats[n]['boundary_total'])
                for n in names
            ],
        ]
        headers = ['Показатель', 'Перцеп.', 'Фишер', 'ЛП']
        table = table_ax.table(cellText=rows, colLabels=headers,
                               colWidths=[0.37, 0.22, 0.215, 0.195],
                               cellLoc='center', colLoc='center',
                               bbox=[0, 0, 1, 1])
        table.auto_set_font_size(False)
        table.set_fontsize(8.5)
        for (row, col), cell in table.get_celld().items():
            cell.set_edgecolor('#d1d5db')
            cell.set_linewidth(0.65)
            cell.set_facecolor('#edf2f8' if row == 0 else
                               '#f6f8fb' if row % 2 == 0 else '#ffffff')
            cell.set_text_props(weight='bold' if row == 0 else 'normal')
            if col == 0 and row > 0:
                cell.get_text().set_ha('left')
                cell.PAD = 0.065
        fig.text(0.766, 0.209,
                 'ЛП: линейное программирование, симплекс-метод.',
                 fontsize=8.3, color='#64748b', va='top')
    else:
        fig.text(0.767, 0.70, 'Нет разделяющих плоскостей',
                 fontsize=10.5, weight='bold')

    fig.text(0.5, 0.027,
             'Вращайте мышью; флажками справа включайте гиперплоскости.',
             ha='center', fontsize=9)
    if image_path:
        fig.savefig(str(image_path), dpi=175)
        print('График сохранён:', image_path)
    if show:
        plt.show()
    else:
        plt.close(fig)
    return plane_artists


def run(expression, truth_csv='truth_table_4d.csv',
        metrics_csv='comparison_4d.csv', image_path='hypercube_comparison.png',
        projection_path='fisher_projections.png', show=True,view='perceptron'):
    X,edges=build_cube()
    y=function_labels(expression,X)
    show_table(X,y)
    save_table(truth_csv,X,y)
    boundary=boundary_edges(edges,y)
    print('\nВершин:',len(X),'| рёбер:',len(edges),'| граничных:',len(boundary))
    print_grid(['Ребро','Изменяется координата'],
               [['%s — %s'%(''.join(map(str,X[i])),''.join(map(str,X[j]))),
                 'x%d'%(int(np.flatnonzero(X[i]!=X[j])[0])+1)] for i,j in boundary])
    if len(np.unique(y))==1:
        print('Один класс: две дискриминантные группы отсутствуют.')
        save_stats(metrics_csv,{})
        show_hypercube(X,y,edges,boundary,{}, {},expression,image_path,show,view)
        return dict(X=X,y=y,edges=edges,boundary=boundary,separable=False,models={})
    separable,witness=linear_separability(X,y)
    print('\nСТРОГАЯ ЛИНЕЙНАЯ РАЗДЕЛИМОСТЬ:', 'ДА' if separable else 'НЕТ')
    if not separable:
        print('Нельзя построить безошибочное линейное разделение.')
        save_stats(metrics_csv,{})
        show_hypercube(X,y,edges,boundary,{}, {},expression,image_path,show,view)
        return dict(X=X,y=y,edges=edges,boundary=boundary,separable=False,models={})
    perceptron,history,ok=train_perceptron(X,y)
    if not ok:
        raise RuntimeError('Перцептрон не сошёлся за %d эпох'%MAX_EPOCHS)
    fisher,fd=train_fisher(X,y)
    simplex,ld=train_simplex(X,y,boundary)
    models={'Перцептрон':perceptron,'Фишер':fisher,'Симплекс':simplex}
    stats={}
    for name,theta in models.items():
        pred=predict_threshold(X,theta)
        err=int(np.count_nonzero(pred!=y))
        cr=boundary_intersections(X,edges,y,theta)
        stats[name]=dict(correct=len(X)-err,errors=err,margin=unit_signed_margin(theta,X,y),
                         J=fisher_criterion(theta,fd['SW'],fd['m1']-fd['m0']),
                         boundary_cross=sum(v is not None for v in cr.values()),
                         boundary_total=len(boundary),
                         epochs=len(history) if name=='Перцептрон' else None,
                         weights=theta.tolist())
    print('\nПерцептрон: пороговая активация, eta=%.2f, эпох %d'%(ETA,len(history)))
    print_fisher_details(fd)
    print_simplex_details(ld)
    print_models(X,y,edges,models,stats,boundary)
    save_stats(metrics_csv,stats)
    fd['X']=X
    fd['labels']=y
    save_projection(projection_path,fd)
    show_hypercube(X,y,edges,boundary,models,stats,expression,image_path,show,view)
    return dict(X=X,y=y,edges=edges,boundary=boundary,separable=True,
                models=models,stats=stats,history=history,fisher=fd,simplex=ld)


def main():
    parser=argparse.ArgumentParser(description='Классификация 4D-гиперкуба: перцептрон, Фишер, симплекс')
    parser.add_argument('--expr',help='Булева функция от x1,x2,x3,x4')
    parser.add_argument('--no-show',action='store_true')
    parser.add_argument('--view',choices=['perceptron','fisher','simplex','all'],default='perceptron')
    parser.add_argument('--truth-csv',default='truth_table_4d.csv')
    parser.add_argument('--metrics-csv',default='comparison_4d.csv')
    parser.add_argument('--png',default='hypercube_comparison.png')
    parser.add_argument('--projection-png',default='fisher_projections.png')
    args=parser.parse_args()
    expr=args.expr
    if expr is None:
        print('Введите булеву функцию (and, or, not, &, |, ~, ^, ¬, ∧, ∨).')
        print('Вариант 2:',EXAMPLE_FUNCTION)
        try:
            expr=input('f(x1,x2,x3,x4) = ').strip() or EXAMPLE_FUNCTION
        except EOFError:
            expr=EXAMPLE_FUNCTION
    try:
        run(expr,truth_csv=Path(args.truth_csv),metrics_csv=Path(args.metrics_csv),
            image_path=Path(args.png),projection_path=Path(args.projection_png),
            show=not args.no_show,view=args.view)
    except (SyntaxError,ValueError) as exc:
        parser.error('Некорректная функция или параметры: '+str(exc))


if __name__=='__main__':
    main()
