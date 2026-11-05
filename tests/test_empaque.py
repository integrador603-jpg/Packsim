import numpy as np
import pytest
import trimesh

from packsim.catalogo import construir
from packsim.empaque import elegir, evaluar
from packsim.modelos import Pieza


def bloque(L, W, H):
    return Pieza(nombre="bloque", malla=trimesh.creation.box((L, W, H)), masa_kg=0.1, origen_masa="cargada")


def test_bloque_exacto_llena_la_caja():
    B = [300, 200, 100]
    alts = {a.id: a for a in evaluar(B, bloque(100, 50, 20), 0, False)}
    assert alts["grilla"].piezas == 60          # 6e6 / 1e5: lleno exacto
    assert alts["mixtos"].piezas == 60


def test_bloques_mixtos_supera_la_grilla_y_no_choca(verificar):
    B = [200, 150, 100]
    p = bloque(37, 23, 11)
    alts = {a.id: a for a in evaluar(B, p, 0.5, False)}
    assert alts["mixtos"].piezas > alts["grilla"].piezas
    assert alts["mixtos"].piezas <= int(np.prod(B) // (37.5 * 23.5 * 11.5)) + 1
    assert verificar(p, alts["mixtos"].colocaciones, B) == (0, 0)


def test_cabeza_cola_en_tornillos(verificar):
    B = [300, 200, 150]
    p = construir("tornillo_hexagonal", {"metrica": "M10", "largo": 50})
    alts = {a.id: a for a in evaluar(B, p, 1.0, False)}
    assert alts["cabeza_cola"].piezas > alts["grilla"].piezas * 1.3
    assert elegir(list(alts.values()), p, "cantidad").id == "cabeza_cola"
    assert verificar(p, alts["cabeza_cola"].colocaciones, B) == (0, 0)


@pytest.mark.parametrize("familia, valores, B", [
    ("arandela_plana", {"metrica": "M16"}, [200, 150, 60]),
    ("rodamiento", {"designacion": "6206"}, [300, 200, 150]),
    ("tornillo_allen", {"metrica": "M8", "largo": 30}, [200, 150, 100]),
])
def test_todas_las_estrategias_sin_colisiones(verificar, familia, valores, B):
    p = construir(familia, valores)
    for a in evaluar(B, p, 1.0, False):
        assert a.piezas > 0
        assert verificar(p, a.colocaciones, B) == (0, 0), a.id


def test_mantener_posicion_no_acuesta_ni_invierte():
    p = construir("tornillo_hexagonal", {"metrica": "M10", "largo": 30})
    for a in evaluar([300, 200, 150], p, 1.0, True):
        assert a.id != "cabeza_cola"
        assert all(c.rotacion[2, 2] == 1 for c in a.colocaciones), a.id


def test_prioridad_picking_prefiere_menos_orientaciones():
    p = bloque(37, 23, 11)
    alts = evaluar([200, 150, 100], p, 0.5, False)
    elegido = elegir(alts, p, "picking")
    maximo = max(a.piezas for a in alts)
    assert elegido.piezas >= 0.95 * maximo
    assert elegido.orientaciones == min(a.orientaciones for a in alts if a.piezas >= 0.95 * maximo)


def test_pieza_que_no_entra():
    p = bloque(500, 50, 50)
    alts = evaluar([300, 200, 100], p, 0, False)
    assert all(a.piezas == 0 for a in alts)
    assert elegir(alts, p, "cantidad") is None
