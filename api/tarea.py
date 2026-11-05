"""
Una simulación completa, pensada para correr en un proceso aparte.

Recibe los bytes del archivo (o los datos del catálogo) y devuelve el resultado, la malla liviana
para el visor y advertencias. No escribe nada en disco salvo las carpetas temporales de los
conversores, que packsim.lectura borra siempre.
"""
from __future__ import annotations

import io

import trimesh

from packsim.catalogo import ErrorCatalogo, construir
from packsim.lectura import ErrorLectura, advertencias, leer_pieza
from packsim.modelos import Criterios, Embalaje
from packsim.motor import ErrorSimulacion, info_pieza, simular

CARAS_MAX_VISOR = 40_000


def malla_visor(m: trimesh.Trimesh) -> bytes:
    """GLB liviano para dibujar la pieza (se simplifica si es muy pesada)."""
    if len(m.faces) > CARAS_MAX_VISOR:
        try:
            m = m.simplify_quadric_decimation(face_count=CARAS_MAX_VISOR)
        except Exception:
            pass
    return trimesh.Scene(m).export(file_type="glb")


def correr(params: dict, datos: bytes | None, nombre_archivo: str | None, avisar=None) -> dict:
    try:
        pz = params["pieza"]
        if pz["origen"] == "catalogo":
            pieza = construir(pz["familia"], pz.get("valores") or {}, pz.get("material", "acero"))
        else:
            pieza = leer_pieza(datos, nombre_archivo, pz.get("unidades", "mm"), pz.get("material", "acero"),
                               pz.get("peso_kg"), pz.get("nombre"))
        avisos = advertencias(pieza) if pz["origen"] != "catalogo" else []
        if not params.get("embalaje"):                  # solo análisis de la pieza (paso 1 de la interfaz)
            return {"ok": True, "resultado": {"pieza": info_pieza(pieza)}, "advertencias": avisos, "glb": malla_visor(pieza.malla)}
        e, c = params["embalaje"], params["criterios"]
        emb = Embalaje(tuple(e["interior_mm"]), e.get("tipo", "carton"), e.get("nombre", "A medida"),
                       e.get("carga_max_kg") or 0.0, e.get("tara_kg") or 0.0, e.get("relleno_kg") or 0.0)
        crit = Criterios(modo=c.get("modo", "ordenado"), holgura_mm=c.get("holgura_mm", 1.0),
                         manipulacion=c.get("manipulacion", "manual"),
                         peso_bruto_manipulable_kg=c.get("peso_bruto_manipulable_kg") or 0.0,
                         mantener_posicion=bool(c.get("mantener_posicion")), prioridad=c.get("prioridad", "cantidad"),
                         piezas_actuales=c.get("piezas_actuales") or 0, validar_fisica=bool(c.get("validar_fisica")))
        resultado = simular(pieza, emb, crit, avisar=avisar)
        animacion = resultado.pop("_animacion", None)
        return {"ok": True, "resultado": resultado, "advertencias": avisos,
                "glb": malla_visor(pieza.malla), "animacion": animacion}
    except (ErrorLectura, ErrorCatalogo, ErrorSimulacion) as e:
        return {"ok": False, "error": str(e), "tipo": "datos"}
    except MemoryError:
        return {"ok": False, "error": "La pieza es demasiado pesada para procesar. Exportala con menos detalle.", "tipo": "limite"}
