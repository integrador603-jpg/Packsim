"""
Estrategias de acomodo ordenado.

Marco: el embalaje B = (largo, ancho, alto) con ejes 0, 1, 2. La pieza se trata por su caja
envolvente p = (ex, ey, ez), salvo las estrategias que aprovechan la forma real:
tresbolillo (piezas redondas) y cabeza-cola (piezas con cabeza).
"""
from __future__ import annotations

import itertools
import math

import numpy as np

from .modelos import Alternativa, Colocacion, Pieza

PERMS = [(0, 1, 2), (1, 0, 2), (2, 1, 0), (0, 2, 1), (1, 2, 0), (2, 0, 1)]
EJES = ["a lo largo", "a lo ancho", "vertical"]


def rot_perm(pm) -> np.ndarray:
    """Rotación que lleva el eje pm[i] de la pieza al eje i del embalaje (det = +1)."""
    R = np.zeros((3, 3), dtype=int)
    for i in range(3):
        R[i, pm[i]] = 1
    if round(np.linalg.det(R)) < 0:
        R[0] *= -1
    return R


def rot_eje(eje_pieza: int, t: int) -> np.ndarray:
    """Rotación que lleva el eje `eje_pieza` de la pieza al eje `t` del embalaje."""
    otros_p = [a for a in range(3) if a != eje_pieza]
    u, v = (t + 1) % 3, (t + 2) % 3
    R = np.zeros((3, 3), dtype=int)
    R[t, eje_pieza] = 1; R[u, otros_p[0]] = 1; R[v, otros_p[1]] = 1
    if round(np.linalg.det(R)) < 0:
        R[u] *= -1
    return R


def perms_validas(p, mantener_posicion: bool):
    vistas, out = set(), []
    for i, pm in enumerate(PERMS):
        if mantener_posicion and pm[2] != 2:
            continue
        clave = tuple(round(p[a], 4) for a in pm)
        if clave in vistas:
            continue
        vistas.add(clave)
        out.append((i, pm))
    return out


def _emitir(org, d, cnt, idx, pm, p, out):
    R = rot_perm(pm)
    half = [p[pm[i]] / 2 for i in range(3)]
    for i in range(cnt[0]):
        for j in range(cnt[1]):
            for k in range(cnt[2]):
                c = np.array([org[0] + i * d[0] + half[0], org[1] + j * d[1] + half[1], org[2] + k * d[2] + half[2]])
                out.append(Colocacion(c, R, f"p{idx}"))


# ─────────────── grilla simple ───────────────

def grilla(B, p, g, perms) -> tuple[list, dict]:
    mejor = (0, None)
    for idx, pm in perms:
        d = [p[pm[i]] + g for i in range(3)]
        n = [int(math.floor((B[i] + g + 1e-9) / d[i])) for i in range(3)]
        tot = n[0] * n[1] * n[2]
        if tot > mejor[0]:
            mejor = (tot, (idx, pm, d, n))
    out = []
    if mejor[1]:
        idx, pm, d, n = mejor[1]
        _emitir((0, 0, 0), d, n, idx, pm, p, out)
    return out, ({"grilla": mejor[1][3], "orientacion_mm": [p[a] for a in mejor[1][1]]} if mejor[1] else {})


# ─────────────── bloques mixtos (guillotina) ───────────────

def bloques_mixtos(B, p, g, perms, presupuesto: int = 120_000) -> list:
    """Divide el embalaje en bloques de distinta orientación y rellena los huecos (búsqueda con memoria)."""
    D0 = tuple(b + g for b in B)
    ds = [(idx, pm, tuple(p[pm[i]] + g for i in range(3))) for idx, pm in perms]
    minD = min(p) + g
    vd = ds[0][2][0] * ds[0][2][1] * ds[0][2][2]
    memo: dict = {}
    contador = [0]

    def clave(D):
        return tuple(int(round(x * 1000)) for x in D)

    def hoja(D):
        mejor = (0, None)
        for idx, pm, d in ds:
            n = [int((D[i] + 1e-9) // d[i]) for i in range(3)]
            t = n[0] * n[1] * n[2]
            if t > mejor[0]:
                mejor = (t, ("grilla", idx, pm, d, n))
        return mejor

    def rec(D):
        if min(D) < minD - 1e-9:
            return 0
        k = clave(D)
        if k in memo:
            return memo[k][0]
        mejor = hoja(D)
        cota = int((D[0] * D[1] * D[2] + 1e-6) // vd)
        if contador[0] < presupuesto and mejor[0] < cota:
            for idx, pm, d in ds:
                n = [int((D[i] + 1e-9) // d[i]) for i in range(3)]
                if 0 in n:
                    continue
                for t in range(3):
                    u, v = (t + 1) % 3, (t + 2) % 3
                    for kk in range(n[t], max(0, n[t] - 4), -1):
                        contador[0] += 1
                        R1 = list(D); R1[t] = D[t] - kk * d[t]
                        R2 = list(D); R2[t] = kk * d[t]; R2[u] = D[u] - n[u] * d[u]
                        R3 = list(D); R3[t] = kk * d[t]; R3[u] = n[u] * d[u]; R3[v] = D[v] - n[v] * d[v]
                        tot = kk * n[u] * n[v] + rec(tuple(R1)) + rec(tuple(R2)) + rec(tuple(R3))
                        if tot > mejor[0]:
                            mejor = (tot, ("corte", idx, pm, d, n, t, kk))
                            if tot >= cota:
                                break
                    if mejor[0] >= cota:
                        break
                if mejor[0] >= cota:
                    break
        memo[k] = mejor
        return mejor[0]

    rec(D0)
    out: list = []

    def realizar(D, org):
        if min(D) < minD - 1e-9:
            return
        rec(D)
        m = memo.get(clave(D))
        if not m or not m[0]:
            return
        if m[1][0] == "grilla":
            _, idx, pm, d, n = m[1]
            _emitir(org, d, n, idx, pm, p, out)
            return
        _, idx, pm, d, n, t, kk = m[1]
        u, v = (t + 1) % 3, (t + 2) % 3
        cnt = list(n); cnt[t] = kk
        _emitir(org, d, cnt, idx, pm, p, out)
        R1 = list(D); R1[t] = D[t] - kk * d[t]; o1 = list(org); o1[t] += kk * d[t]
        R2 = list(D); R2[t] = kk * d[t]; R2[u] = D[u] - n[u] * d[u]; o2 = list(org); o2[u] += n[u] * d[u]
        R3 = list(D); R3[t] = kk * d[t]; R3[u] = n[u] * d[u]; R3[v] = D[v] - n[v] * d[v]; o3 = list(org); o3[v] += n[v] * d[v]
        realizar(tuple(R1), o1); realizar(tuple(R2), o2); realizar(tuple(R3), o3)

    realizar(D0, [0.0, 0.0, 0.0])
    return out


# ─────────────── tresbolillo (piezas redondas) ───────────────

def _hex2d(A, Bv, D, g):
    dd = D + g
    h = dd * math.sqrt(3) / 2
    mejor = (0, [])
    for swap in (False, True):
        a, b = (Bv, A) if swap else (A, Bv)
        if b < D or a < D:
            continue
        n1 = int((a + g + 1e-9) // dd)
        n2 = int((a + g - dd / 2 + 1e-9) // dd)
        filas = 1 + int((b - D) / h + 1e-9)
        pts = []
        for r in range(filas):
            corrida = r % 2 == 1
            for i in range(n2 if corrida else n1):
                x = D / 2 + i * dd + (dd / 2 if corrida else 0)
                y = D / 2 + r * h
                pts.append((y, x) if swap else (x, y))
        if len(pts) > mejor[0]:
            mejor = (len(pts), pts)
    return mejor[1]


def tresbolillo(B, pieza: Pieza, g, mantener_posicion: bool):
    rd = pieza.redonda
    mejor = ([], {})
    for t in range(3):
        if mantener_posicion and t != 2:
            continue
        if mantener_posicion and rd.eje != 2:
            continue
        u, v = (t + 1) % 3, (t + 2) % 3
        n_ax = int((B[t] + g + 1e-9) // (rd.largo + g))
        if not n_ax:
            continue
        plano = _hex2d(B[u], B[v], rd.diametro, g)
        if len(plano) * n_ax <= len(mejor[0]):
            continue
        R = rot_eje(rd.eje, t)
        out = []
        for k in range(n_ax):
            for a, b in plano:
                c = np.zeros(3); c[t] = rd.largo / 2 + k * (rd.largo + g); c[u] = a; c[v] = b
                out.append(Colocacion(c, R, f"h{t}"))
        mejor = (out, {"eje": t, "capas": n_ax, "por_capa": len(plano)})
    return mejor


# ─────────────── cabeza-cola (tornillos) ───────────────

def cabeza_cola(B, pieza: Pieza, g):
    """Alterna la orientación para que la cabeza de cada pieza quede junto al cuerpo de la vecina."""
    cb, rd = pieza.cabeza, pieza.redonda
    if not cb or not rd or rd.largo - cb.alto_cabeza < cb.alto_cabeza:
        return [], {}
    rH, rS, L = cb.radio_cabeza, cb.radio_cuerpo, rd.largo
    c = rH + rS + g
    lleno = 2 * rH + g
    damero_ok = c * math.sqrt(2) >= 2 * rH + g - 1e-9   # las vecinas en diagonal (misma orientación) no chocan
    mejor = ([], {})
    for t in range(3):
        u, v = (t + 1) % 3, (t + 2) % 3
        n_ax = int((B[t] + g + 1e-9) // (L + g))
        if not n_ax:
            continue
        variantes = []
        if damero_ok:
            variantes.append((c, c, lambda i, j: (i + j) % 2, "alternadas en damero"))
        variantes += [(c, lleno, lambda i, j: i % 2, "filas alternadas"), (lleno, c, lambda i, j: j % 2, "filas alternadas")]
        for du, dv, gira, nombre in variantes:
            a = 1 + int((B[u] - 2 * rH + 1e-9) // du) if B[u] >= 2 * rH else 0
            b = 1 + int((B[v] - 2 * rH + 1e-9) // dv) if B[v] >= 2 * rH else 0
            if n_ax * a * b <= len(mejor[0]):
                continue
            R0 = rot_eje(rd.eje, t)
            Rf = R0.copy(); Rf[t] *= -1; Rf[u] *= -1           # 180° alrededor del eje v
            out = []
            for k in range(n_ax):
                for i in range(a):
                    for j in range(b):
                        f = gira(i, j)
                        cc = np.zeros(3); cc[t] = L / 2 + k * (L + g); cc[u] = rH + i * du; cc[v] = rH + j * dv
                        out.append(Colocacion(cc, Rf if f else R0, f"c{t}{f}"))
            mejor = (out, {"eje": t, "variante": nombre, "capas": n_ax})
    return mejor


# ─────────────── todas las estrategias ───────────────

def evaluar(B, pieza: Pieza, holgura: float, mantener_posicion: bool) -> list[Alternativa]:
    p = [float(x) for x in pieza.envolvente_mm]
    perms = perms_validas(p, mantener_posicion)
    alts = []
    pl, info = grilla(B, p, holgura, perms)
    alts.append(Alternativa("grilla", "Grilla simple", "una sola orientación, filas y columnas", pl))
    alts.append(Alternativa("mixtos", "Bloques mixtos", "combina orientaciones y rellena huecos", bloques_mixtos(B, p, holgura, perms)))
    if pieza.redonda:
        pl, info = tresbolillo(B, pieza, holgura, mantener_posicion)
        if pl:
            alts.append(Alternativa("tresbolillo", "Tresbolillo", f"filas intercaladas, eje {EJES[info['eje']]}", pl))
    if pieza.cabeza and not mantener_posicion:
        pl, info = cabeza_cola(B, pieza, holgura)
        if pl:
            alts.append(Alternativa("cabeza_cola", "Cabeza-cola", f"{info['variante']}, eje {EJES[info['eje']]}", pl))
    for a in alts:
        a.colocaciones.sort(key=lambda c: (round(c.centro_mm[2], 3), c.centro_mm[0], c.centro_mm[1]))
    return alts


def fraccion_apoyada(alt: Alternativa, pieza: Pieza) -> float:
    """Fracción de piezas apoyadas sobre su cara más grande (eje más corto vertical)."""
    if not alt.colocaciones:
        return 0.0
    corto = int(np.argmin(pieza.envolvente_mm))
    return sum(1 for c in alt.colocaciones if abs(c.rotacion[2, corto]) == 1) / len(alt.colocaciones)


def elegir(alts: list[Alternativa], pieza: Pieza, prioridad: str) -> Alternativa | None:
    validas = [a for a in alts if a.piezas]
    if not validas:
        return None
    maximo = max(a.piezas for a in validas)
    if prioridad == "cantidad":
        return max(validas, key=lambda a: a.piezas)
    cerca = [a for a in validas if a.piezas >= 0.95 * maximo]
    if prioridad == "picking":
        return min(cerca, key=lambda a: (a.orientaciones, -a.piezas))
    return max(cerca, key=lambda a: (round(fraccion_apoyada(a, pieza), 6), a.piezas))
