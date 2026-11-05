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


def test_memoria_se_controla_por_uso_real_y_no_por_reserva():
    # el error "cannot allocate memory for thread-local data" venía de limitar la reserva (RLIMIT_AS)
    from tests.ayuda_procesos import sin_limite_de_reserva
    r = ejecutar_aislado({}, None, None, tiempo_max_s=10, memoria_mb=512, destino=sin_limite_de_reserva)
    assert r["ok"] and r["as"]


def test_proceso_que_usa_demasiada_memoria_se_corta():
    from tests.ayuda_procesos import gloton
    r = ejecutar_aislado({}, None, None, tiempo_max_s=30, memoria_mb=200, destino=gloton, intervalo_s=0.05)
    assert not r["ok"] and r["tipo"] == "limite" and "200 MB" in r["error"]


def test_falla_del_lector_tiene_mensaje_propio():
    from tests.ayuda_procesos import aborta
    r = ejecutar_aislado({}, None, None, tiempo_max_s=10, memoria_mb=512, destino=aborta)
    assert not r["ok"] and r["tipo"] == "lector"


def test_diagnostico(cliente):
    d = cliente.get("/v1/diagnostico").json()
    assert d["motor_ok"] is True and d["nucleos"] >= 1


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


# ─────────────── etapa 4: física por la API ───────────────

BUJE_CHICO = {"pieza": {"origen": "catalogo", "familia": "buje", "valores": {"diametro": 20, "interior": 10, "largo": 20}},
              "embalaje": {"interior_mm": [100, 80, 60]}}


def test_granel_por_la_api_con_progreso_y_animacion(cliente):
    import struct
    params = {**BUJE_CHICO, "criterios": {"modo": "granel", "manipulacion": "autoelevador"}}
    id_ = simular(cliente, params).json()["id"]
    vio_progreso = False
    fin = time.time() + 180
    while time.time() < fin:
        d = cliente.get(f"/v1/trabajos/{id_}").json()
        vio_progreso |= bool(d.get("texto"))
        if d["estado"] in ("listo", "error"):
            break
        time.sleep(0.2)
    assert d["estado"] == "listo", d
    R = d["resultado"]["resultado"]
    assert R["estrategia_id"] == "granel" and 0 < R["maximo_posible"] <= R["fisica"]["maximo_ordenado"]
    # indicador de calidad: las partes convexas aproximan la malla y el valor varía entre máquinas (local 0,6; GitHub 2,2)
    assert R["fisica"]["penetracion_max_mm"] < 0.15 * 25
    assert vio_progreso
    a = cliente.get(d["animacion"])
    assert a.status_code == 200 and struct.unpack("<IIf", a.content[:12])[0] > 0


def test_validacion_fisica_por_la_api(cliente):
    params = {**BUJE_CHICO, "criterios": {"manipulacion": "autoelevador", "validar_fisica": True}}
    d = esperar(cliente, simular(cliente, params).json()["id"], s=180)
    assert d["estado"] == "listo", d
    f = d["resultado"]["resultado"]["fisica"]
    assert f["tipo"] == "validacion" and f["estado"] in ("se_mantiene", "se_reacomoda", "se_desarma")
    assert f["piezas"] == d["resultado"]["resultado"]["piezas"]
    assert "animacion" in d
