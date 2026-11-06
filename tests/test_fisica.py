"""
Tests de la simulación física. Son los más lentos del proyecto (decenas de segundos):
cada uno valida una propiedad física conocida, no solo que el código corra.
"""
import struct

import numpy as np
import pytest
import trimesh

pytest.importorskip("pybullet")

from packsim.empaque import elegir, evaluar  # noqa: E402
from packsim.fisica import _extrapolar, granel, validar  # noqa: E402
from packsim.modelos import Embalaje, Pieza  # noqa: E402


def esfera(d=20.0):
    return Pieza(nombre="esfera", malla=trimesh.creation.icosphere(subdivisions=3, radius=d / 2), masa_kg=0.03, origen_masa="cargada")


def bloque(L, W, H):
    return Pieza(nombre="bloque", malla=trimesh.creation.box((L, W, H)), masa_kg=0.2, origen_masa="cargada")


def test_esferas_a_granel_dan_la_densidad_conocida():
    """Esferas vibradas lejos de las paredes: ≈0,64 (empaquetamiento aleatorio compacto)."""
    from scipy.spatial import cKDTree
    d, B = 20.0, (120, 100, 100)
    r = granel(esfera(d), Embalaje(B))
    assert not r["extrapolado"]
    C = np.array([c["centro_mm"] for c in r["disposicion"]])
    lo, hi = np.array([1.5 * d] * 3), np.array([B[0] - 1.5 * d, B[1] - 1.5 * d, B[2] - 2.5 * d])
    pts = np.random.default_rng(0).uniform(lo, hi, size=(100_000, 3))
    interior = float((cKDTree(C).query(pts)[0] <= d / 2).mean())
    assert 0.56 < interior < 0.68, interior
    assert r["penetracion_max_mm"] < 1.0                    # nadie atraviesa el fondo ni las paredes
    assert (C >= -1e-6).all() and (C <= np.array(B) + 1e-6).all()


def test_mismos_datos_mismo_resultado():
    a = granel(esfera(), Embalaje((80, 80, 60)), semilla=3)
    b = granel(esfera(), Embalaje((80, 80, 60)), semilla=3)
    assert a["piezas_que_entran"] == b["piezas_que_entran"]


def test_acomodo_justo_se_mantiene_y_uno_flojo_se_reacomoda():
    p = bloque(40, 30, 20)
    justo = (4 * 41 - 1, 4 * 31 - 1, 4 * 21 - 1)          # 4 × 4 × 4 bloques con 1 mm de holgura: caja llena
    alt = elegir(evaluar(list(justo), p, 1.0, False), p, "cantidad")
    assert alt.piezas == 64
    r = validar(p, Embalaje(justo), alt.colocaciones)
    assert r["estado"] == "se_mantiene", r
    assert r["piezas_fuera"] == 0 and r["giro_max_grados"] < 10
    flojo = (160, 120, 80)                                  # deja espacio libre bajo la tapa: en transporte se corre
    alt = elegir(evaluar(list(flojo), p, 1.0, False), p, "cantidad")
    r = validar(p, Embalaje(flojo), alt.colocaciones)
    assert r["estado"] == "se_reacomoda" and r["piezas_fuera"] == 0, r


def test_animacion_tiene_formato_valido():
    r = granel(esfera(), Embalaje((80, 80, 60)))
    a = r["animacion"]
    n, f, fps = struct.unpack("<IIf", a[:12])
    assert n > 0 and f > 0 and fps > 0
    assert len(a) == 12 + 4 * n + f * n * 7 * 4


def test_extrapolacion_con_densidad_uniforme_es_proporcional():
    # red uniforme: sin déficit de bordes, el modelo tiene que dar ρ·V
    paso = 10.0
    xs = np.arange(5, 200, paso)
    C = [{"centro_mm": [x, y, z]} for x in xs for y in np.arange(5, 150, paso) for z in np.arange(5, 120, paso)]
    n = _extrapolar(C, (200, 150, 120), (400, 300, 240), dmax=10)
    assert abs(n - len(C) * 8) / (len(C) * 8) < 0.03


def test_llenado_parcial_se_extrapola_en_altura(monkeypatch):
    from packsim import fisica
    from packsim.catalogo import construir
    # si el volcado se corta antes de llenar (tope de cuerpos o de tiempo), se estima con la densidad del lecho
    p = construir("buje", {"diametro": 20, "interior": 10.5, "largo": 25})
    monkeypatch.setattr(fisica, "CUERPOS_MAX", 40)
    r = fisica.granel(p, Embalaje((100, 80, 200)))
    lp = r["llenado_parcial"]
    assert lp and lp["piezas"] <= 40 and lp["altura_lecho_mm"] < 200
    assert r["piezas_que_entran"] == lp["piezas_caja_llena"] > lp["piezas"]
    assert r["extrapolado"] is False and r["muestra"] is None
