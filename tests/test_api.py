import glob
import io
import json
import logging
import os
import tempfile
import time

import ezdxf
import pytest
from fastapi.testclient import TestClient

from api.app import crear_app
from api.config import Config
from api.trabajos import Almacen, ejecutar_aislado
from packsim.catalogo import construir

CLAVE, KEY = "una-clave-larga", "key-integracion"
TORNILLO = {"pieza": {"origen": "catalogo", "familia": "tornillo_hexagonal", "valores": {"metrica": "M10", "largo": 50}},
            "embalaje": {"interior_mm": [300, 200, 150], "carga_max_kg": 15, "tara_kg": 0.3},
            "criterios": {}}


def cfg(**kw):
    base = dict(clave=CLAVE, api_keys=(KEY,), secreto="s" * 32, cookies_seguras=False, tiempo_max_s=60, limite_por_hora=100)
    base.update(kw)
    return Config(**base)


@pytest.fixture
def cliente():
    with TestClient(crear_app(cfg())) as c:
        assert c.post("/v1/sesion", json={"clave": CLAVE}).status_code == 200
        yield c


def esperar(c, id_, s=60):
    fin = time.time() + s
    while time.time() < fin:
        d = c.get(f"/v1/simulaciones/{id_}").json()
        if d["estado"] in ("listo", "error"):
            return d
        time.sleep(0.2)
    raise AssertionError("la simulación no terminó")


def simular(c, params, archivo=None):
    files = {"archivo": archivo} if archivo else None
    return c.post("/v1/simulaciones", data={"parametros": json.dumps(params)}, files=files)


# ─────────────── acceso ───────────────

def test_sin_sesion_no_hay_acceso():
    with TestClient(crear_app(cfg())) as c:
        assert c.get("/salud").status_code == 200
        assert c.get("/v1/catalogo").status_code == 401
        assert c.post("/v1/sesion", json={"clave": "mala"}).status_code == 401
        assert c.get("/v1/catalogo").status_code == 401


def test_api_key_para_integraciones():
    with TestClient(crear_app(cfg())) as c:
        assert c.get("/v1/catalogo", headers={"Authorization": f"Bearer {KEY}"}).status_code == 200
        assert c.get("/v1/catalogo", headers={"Authorization": "Bearer otra"}).status_code == 401


def test_catalogo_y_tara(cliente):
    d = cliente.get("/v1/catalogo").json()
    assert {f["id"] for f in d["familias"]} >= {"tornillo_hexagonal", "rodamiento"}
    assert any(e["tipo"] == "madera" for e in d["embalajes"])
    t = cliente.get("/v1/embalajes/tara", params={"largo": 600, "ancho": 400, "alto": 300, "tipo": "carton"}).json()
    assert 0.8 < t["tara_kg"] < 1.4


# ─────────────── simulaciones ───────────────

def test_simulacion_de_catalogo_y_malla(cliente):
    r = simular(cliente, TORNILLO)
    assert r.status_code == 202
    d = esperar(cliente, r.json()["id"])
    assert d["estado"] == "listo", d
    res = d["resultado"]["resultado"]
    assert res["maximo_posible"] == 540 and res["peso_bruto_kg"] <= 15
    m = cliente.get(d["malla_visor"])
    assert m.status_code == 200 and m.content[:4] == b"glTF"


def test_simulacion_de_archivo_sin_rastros(cliente, caplog):
    antes = set(glob.glob(os.path.join(tempfile.gettempdir(), "packsim_*")))
    stl = construir("buje", {"diametro": 30, "interior": 12, "largo": 40}).malla.export(file_type="stl")
    params = {"pieza": {"origen": "archivo", "peso_kg": 0.2}, "embalaje": {"interior_mm": [300, 200, 150]},
              "criterios": {"manipulacion": "autoelevador"}}
    with caplog.at_level(logging.INFO):
        d = esperar(cliente, simular(cliente, params, ("PLANO_CONFIDENCIAL_123.stl", stl, "application/octet-stream")).json()["id"])
    assert d["estado"] == "listo", d
    assert d["resultado"]["resultado"]["piezas"] > 0
    assert d["resultado"]["pieza"]["origen_peso"] == "cargada"
    assert "PLANO_CONFIDENCIAL" not in caplog.text                       # el nombre no aparece en logs
    assert "PLANO_CONFIDENCIAL" not in json.dumps(d)                     # ni en la respuesta
    assert set(glob.glob(os.path.join(tempfile.gettempdir(), "packsim_*"))) == antes


def test_plano_2d_termina_con_error_claro(cliente):
    doc = ezdxf.new(); doc.modelspace().add_line((0, 0), (100, 0))
    s = io.StringIO(); doc.write(s)
    params = {**TORNILLO, "pieza": {"origen": "archivo"}}
    d = esperar(cliente, simular(cliente, params, ("plano.dxf", s.getvalue().encode(), "application/dxf")).json()["id"])
    assert d["estado"] == "error" and "plano 2D" in d["error"]


def test_validaciones(cliente):
    params = {**TORNILLO, "pieza": {"origen": "archivo"}}
    assert simular(cliente, params).status_code == 422                                           # falta el archivo
    assert simular(cliente, params, ("pieza.pdf", b"x", "application/pdf")).status_code == 415   # formato
    assert simular(cliente, {**TORNILLO, "criterios": {"modo": "granel"}}).status_code == 422
    r = simular(cliente, {**TORNILLO, "embalaje": {"interior_mm": [300, -1, 150]}})
    assert r.status_code == 422 and "medidas" in r.json()["detalle"]
    r = cliente.post("/v1/simulaciones", data={"parametros": "no es json"})
    assert r.status_code == 422


def test_tamano_maximo():
    with TestClient(crear_app(cfg(tamano_max_mb=1))) as c:
        c.post("/v1/sesion", json={"clave": CLAVE})
        r = simular(c, {**TORNILLO, "pieza": {"origen": "archivo"}}, ("grande.stl", b"0" * (2 * 1024 * 1024), "application/octet-stream"))
        assert r.status_code == 413


def test_limite_por_hora():
    with TestClient(crear_app(cfg(limite_por_hora=2))) as c:
        c.post("/v1/sesion", json={"clave": CLAVE})
        codigos = [simular(c, TORNILLO).status_code for _ in range(3)]
        assert codigos == [202, 202, 429]


def test_borrar_resultado(cliente):
    id_ = simular(cliente, TORNILLO).json()["id"]
    esperar(cliente, id_)
    assert cliente.delete(f"/v1/simulaciones/{id_}").status_code == 200
    assert cliente.get(f"/v1/simulaciones/{id_}").status_code == 404


# ─────────────── aislamiento y vencimiento ───────────────

def test_proceso_que_tarda_se_cancela():
    from tests.ayuda_procesos import lento
    t0 = time.time()
    r = ejecutar_aislado({}, None, None, tiempo_max_s=2, memoria_mb=512, destino=lento)
    assert not r["ok"] and "tiempo máximo" in r["error"]
    assert time.time() - t0 < 10


def test_proceso_que_revienta_no_tumba_la_api():
    from tests.ayuda_procesos import revienta
    r = ejecutar_aislado({}, None, None, tiempo_max_s=10, memoria_mb=512, destino=revienta)
    assert not r["ok"] and "inesperada" in r["error"]


def test_resultados_vencen():
    a = Almacen(vencimiento_s=0, maximo=10)
    t = a.nuevo(); t.estado = "listo"; t.terminado = time.time() - 1
    assert a.obtener(t.id) is None


def test_tope_de_trabajos_en_memoria():
    a = Almacen(vencimiento_s=3600, maximo=2)
    a.nuevo(); a.nuevo()
    with pytest.raises(OverflowError):
        a.nuevo()


# ─────────────── etapa 3: análisis de pieza e interfaz ───────────────

def test_analisis_de_pieza_sin_embalaje(cliente):
    r = cliente.post("/v1/piezas", data={"parametros": json.dumps({"pieza": TORNILLO["pieza"]})})
    assert r.status_code == 202
    d = esperar(cliente, r.json()["id"])
    assert d["estado"] == "listo", d
    assert set(d["resultado"]) == {"pieza"}
    assert d["resultado"]["pieza"]["nombre"] == "Tornillo hexagonal M10 × 50"
    assert cliente.get(d["malla_visor"]).content[:4] == b"glTF"


def test_interfaz_servida_con_politica_de_contenido():
    with TestClient(crear_app(cfg())) as c:
        r = c.get("/")
        assert r.status_code == 200 and "Packsim" in r.text
        csp = r.headers["content-security-policy"]
        assert "script-src 'self' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net" in csp and "unsafe-eval" not in csp
        assert c.get("/app.js").status_code == 200
        assert "onclick=" not in r.text                     # sin scripts incrustados (los bloquearía la política)
