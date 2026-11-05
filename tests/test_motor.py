import json

import pytest

from packsim.catalogo import construir
from packsim.modelos import Criterios, Embalaje
from packsim.motor import ErrorSimulacion, simular


@pytest.fixture(scope="module")
def tornillo():
    return construir("tornillo_hexagonal", {"metrica": "M10", "largo": 50})


def test_saturacion_y_peso_bruto_con_limite_manual(tornillo):
    r = simular(tornillo, Embalaje((300, 200, 150), carga_max_kg=15, tara_kg=0.3), Criterios())["resultado"]
    assert r["maximo_posible"] == 540
    assert r["limitado_por"] == "peso bruto manipulable"
    assert r["peso_bruto_kg"] <= 15.0 + 1e-9
    assert r["peso_bruto_kg"] == pytest.approx(r["peso_piezas_kg"] + 0.3)
    assert r["saturacion"] == pytest.approx(r["piezas"] / 540, abs=1e-4)


def test_autoelevador_ignora_el_limite_manual(tornillo):
    r = simular(tornillo, Embalaje((300, 200, 150), tara_kg=0.3), Criterios(manipulacion="autoelevador"))["resultado"]
    assert r["limitado_por"] == "espacio"
    assert r["piezas"] == r["maximo_posible"]
    assert r["saturacion"] == 1.0


def test_embalaje_vacio_supera_el_limite(tornillo):
    r = simular(tornillo, Embalaje((800, 600, 500), "madera", tara_kg=22, relleno_kg=1.5), Criterios())["resultado"]
    assert r["embalaje_vacio_excede_limite_manual"] is True
    assert r["piezas"] == 0
    assert r["peso_bruto_kg"] == pytest.approx(23.5)


def test_auditoria(tornillo):
    r = simular(tornillo, Embalaje((300, 200, 150)), Criterios(manipulacion="autoelevador", piezas_actuales=270))["resultado"]
    assert r["auditoria"] is True
    assert r["saturacion"] == pytest.approx(0.5)
    assert r["piezas_que_faltan"] == 270


def test_contrato_serializable_y_disposicion_ordenada(tornillo):
    r = simular(tornillo, Embalaje((300, 200, 150)), Criterios(manipulacion="autoelevador"))
    json.dumps(r)
    disp = r["resultado"]["disposicion"]
    assert len(disp) == 540
    zs = [d["centro_mm"][2] for d in disp]
    assert zs == sorted(zs)
    assert r["version"] == "1.0"


def test_errores_claros(tornillo):
    with pytest.raises(ErrorSimulacion):
        simular(tornillo, Embalaje((0, 200, 150)), Criterios())
    with pytest.raises(ErrorSimulacion, match="granel"):
        simular(tornillo, Embalaje((300, 200, 150)), Criterios(modo="granel"))
