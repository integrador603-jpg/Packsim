import pytest

from packsim.catalogo import FAMILIAS, ErrorCatalogo, construir


@pytest.mark.parametrize("familia", list(FAMILIAS))
def test_todas_las_familias_son_solidos_cerrados(familia):
    p = construir(familia)
    assert p.malla.is_watertight
    assert p.volumen_mm3 > 0 and p.masa_kg > 0
    assert p.redonda is not None


@pytest.mark.parametrize("familia, valores, kg_ref, tol", [
    # pesos de tabla por pieza (acero, sin descontar rosca)
    ("tornillo_hexagonal", {"metrica": "M10", "largo": 50}, 0.0400, 0.10),
    ("arandela_plana", {"metrica": "M10"}, 0.0035, 0.10),
    ("tuerca_hexagonal", {"metrica": "M10"}, 0.0100, 0.15),
])
def test_pesos_cercanos_a_tabla(familia, valores, kg_ref, tol):
    p = construir(familia, valores)
    assert abs(p.masa_kg - kg_ref) / kg_ref < tol, p.masa_kg


def test_rodamiento_usa_peso_de_catalogo():
    p = construir("rodamiento", {"designacion": "6204"})
    assert p.masa_kg == pytest.approx(0.106)
    assert p.origen_masa == "catálogo"
    assert list(p.envolvente_mm.round(2)) == [47, 47, 14]


def test_tornillo_tiene_cabeza_para_cabeza_cola():
    p = construir("tornillo_hexagonal", {"metrica": "M12", "largo": 80})
    assert p.cabeza is not None
    assert p.cabeza.radio_cabeza > p.cabeza.radio_cuerpo
    assert p.envolvente_mm[2] == pytest.approx(80 + 7.5, abs=0.01)


def test_material_cambia_el_peso():
    acero = construir("buje", {"diametro": 20, "interior": 10, "largo": 25}, "acero")
    alu = construir("buje", {"diametro": 20, "interior": 10, "largo": 25}, "aluminio")
    assert alu.masa_kg == pytest.approx(acero.masa_kg * 2.7 / 7.85, rel=1e-6)


def test_opcion_invalida():
    with pytest.raises(ErrorCatalogo):
        construir("tornillo_hexagonal", {"metrica": "M7"})
    with pytest.raises(ErrorCatalogo):
        construir("buje", {"diametro": 10, "interior": 12, "largo": 5})
