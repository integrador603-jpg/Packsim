"""
Catálogo de minutería normalizada.

Medidas nominales en mm según norma. Las piezas se construyen con el eje a lo largo de Z
(cabeza abajo, en z = 0), como sólidos cerrados para que el volumen y las colisiones sean exactos.
La rosca no se modela: el peso queda unos pocos por ciento por encima del real.
"""
from __future__ import annotations

import math

import numpy as np
import trimesh

from .modelos import Cabeza, Pieza, Redonda

DENSIDADES = {  # g/cm³
    "acero": 7.85, "inox": 7.95, "laton": 8.5, "bronce": 8.8,
    "aluminio": 2.7, "nylon": 1.14, "fundicion": 7.2,
}
NOMBRES_MATERIAL = {
    "acero": "Acero", "inox": "Acero inoxidable", "laton": "Latón", "bronce": "Bronce",
    "aluminio": "Aluminio", "nylon": "Nylon / plástico", "fundicion": "Fundición gris",
}

METRICAS = ["M6", "M8", "M10", "M12", "M16", "M20"]
# ISO 4017 / 4032: d = diámetro, s = entre caras, k = alto de cabeza, m = alto de tuerca
T_HEX = {"M6": dict(d=6, s=10, k=4, m=5.2), "M8": dict(d=8, s=13, k=5.3, m=6.8),
         "M10": dict(d=10, s=16, k=6.4, m=8.4), "M12": dict(d=12, s=18, k=7.5, m=10.8),
         "M16": dict(d=16, s=24, k=10, m=14.8), "M20": dict(d=20, s=30, k=12.5, m=18)}
T_ALLEN = {"M6": 10, "M8": 13, "M10": 16, "M12": 18, "M16": 24, "M20": 30}          # ISO 4762 dk
T_985 = {"M6": 6, "M8": 8, "M10": 10, "M12": 12, "M16": 16, "M20": 20}              # DIN 985 alto total
T_125 = {"M6": (6.4, 12, 1.6), "M8": (8.4, 16, 1.6), "M10": (10.5, 20, 2),           # ISO 7089 d1, d2, h
         "M12": (13, 24, 2.5), "M16": (17, 30, 3), "M20": (21, 37, 3)}
T_127 = {"M6": (6.1, 11.8, 1.6), "M8": (8.1, 14.8, 2), "M10": (10.2, 18.1, 2.2),      # DIN 127 B d1, d2, s
         "M12": (12.2, 21.1, 2.5), "M16": (16.2, 27.4, 3.5), "M20": (20.2, 33.6, 4)}
T_62 = {"6201": (12, 32, 10, 0.037), "6202": (15, 35, 11, 0.045), "6203": (17, 40, 12, 0.065),  # d, D, B, kg
        "6204": (20, 47, 14, 0.106), "6205": (25, 52, 15, 0.128), "6206": (30, 62, 16, 0.199),
        "6207": (35, 72, 17, 0.288), "6208": (40, 80, 18, 0.366)}
LARGOS_HEX = [16, 20, 25, 30, 35, 40, 50, 60, 70, 80, 100, 120, 150]
LARGOS_ALLEN = [10, 12, 16, 20, 25, 30, 35, 40, 50, 60, 80, 100]
LARGOS_VARILLA = [100, 250, 500, 1000]

SEG = 48  # segmentos de los cilindros


def esquina(s: float) -> float:
    """Diámetro entre vértices de un hexágono de entre caras s."""
    return s * 2 / math.sqrt(3)


# ─────────────── primitivas (eje Z) ───────────────

def _cil(D, h, z0):
    m = trimesh.creation.cylinder(radius=D / 2, height=h, sections=SEG)
    m.apply_translation([0, 0, z0 + h / 2])
    return m


def _hex(e, h, z0):
    m = trimesh.creation.cylinder(radius=e / 2, height=h, sections=6)
    m.apply_translation([0, 0, z0 + h / 2])
    return m


def _anillo(D, di, h, z0, sections=SEG):
    m = trimesh.creation.annulus(r_min=di / 2, r_max=D / 2, height=h, sections=sections)
    m.apply_translation([0, 0, z0 + h / 2])
    return m


def _union(partes):
    return partes[0] if len(partes) == 1 else trimesh.boolean.union(partes, engine="manifold")


def _resta(a, b):
    return trimesh.boolean.difference([a, b], engine="manifold")


# ─────────────── familias ───────────────

FAMILIAS = {
    "tornillo_hexagonal": {
        "nombre": "Tornillo hexagonal", "norma": "ISO 4017 · DIN 933",
        "campos": [{"id": "metrica", "nombre": "Métrica", "opciones": METRICAS, "defecto": "M10"},
                   {"id": "largo", "nombre": "Largo bajo cabeza", "opciones": LARGOS_HEX, "defecto": 50, "unidad": "mm"}],
    },
    "tornillo_allen": {
        "nombre": "Tornillo Allen", "norma": "ISO 4762 · DIN 912",
        "campos": [{"id": "metrica", "nombre": "Métrica", "opciones": METRICAS, "defecto": "M8"},
                   {"id": "largo", "nombre": "Largo bajo cabeza", "opciones": LARGOS_ALLEN, "defecto": 30, "unidad": "mm"}],
    },
    "tuerca_hexagonal": {
        "nombre": "Tuerca hexagonal", "norma": "ISO 4032 · DIN 934",
        "campos": [{"id": "metrica", "nombre": "Métrica", "opciones": METRICAS, "defecto": "M10"}],
    },
    "tuerca_autofrenante": {
        "nombre": "Tuerca autofrenante", "norma": "DIN 985",
        "campos": [{"id": "metrica", "nombre": "Métrica", "opciones": METRICAS, "defecto": "M10"}],
    },
    "arandela_plana": {
        "nombre": "Arandela plana", "norma": "ISO 7089 · DIN 125",
        "campos": [{"id": "metrica", "nombre": "Para métrica", "opciones": METRICAS, "defecto": "M10"}],
    },
    "arandela_grower": {
        "nombre": "Arandela grower", "norma": "DIN 127 B",
        "campos": [{"id": "metrica", "nombre": "Para métrica", "opciones": METRICAS, "defecto": "M10"}],
    },
    "varilla_roscada": {
        "nombre": "Varilla roscada", "norma": "DIN 975",
        "campos": [{"id": "metrica", "nombre": "Métrica", "opciones": METRICAS, "defecto": "M10"},
                   {"id": "largo", "nombre": "Largo", "opciones": LARGOS_VARILLA, "defecto": 250, "unidad": "mm"}],
    },
    "buje": {
        "nombre": "Buje / separador", "norma": "A medida",
        "campos": [{"id": "diametro", "nombre": "Diámetro exterior", "defecto": 20, "unidad": "mm"},
                   {"id": "interior", "nombre": "Diámetro interior", "defecto": 10.5, "unidad": "mm"},
                   {"id": "largo", "nombre": "Largo", "defecto": 25, "unidad": "mm"}],
    },
    "rodamiento": {
        "nombre": "Rodamiento rígido de bolas", "norma": "Serie 62xx",
        "campos": [{"id": "designacion", "nombre": "Designación", "opciones": list(T_62), "defecto": "6204"}],
    },
}


class ErrorCatalogo(ValueError):
    pass


def _param(familia, valores, campo):
    for c in FAMILIAS[familia]["campos"]:
        if c["id"] == campo:
            v = valores.get(campo, c["defecto"])
            if "opciones" in c and v not in c["opciones"] and str(v) not in [str(o) for o in c["opciones"]]:
                raise ErrorCatalogo(f"{c['nombre']}: valor {v!r} no válido. Opciones: {c['opciones']}")
            if "opciones" in c:
                v = next(o for o in c["opciones"] if str(o) == str(v))
            return v
    raise ErrorCatalogo(f"Campo desconocido: {campo}")


def construir(familia: str, valores: dict | None = None, material: str = "acero") -> Pieza:
    """Crea una pieza del catálogo. `valores` usa los ids de FAMILIAS[familia]['campos']."""
    if familia not in FAMILIAS:
        raise ErrorCatalogo(f"Familia desconocida: {familia}")
    if material not in DENSIDADES:
        raise ErrorCatalogo(f"Material desconocido: {material}")
    v = valores or {}
    f = FAMILIAS[familia]
    rho = DENSIDADES[material] / 1000.0  # g/mm³
    cabeza = None
    masa_cat = None
    vol_override = None

    if familia in ("tornillo_hexagonal", "tornillo_allen"):
        m_ = _param(familia, v, "metrica"); L = float(_param(familia, v, "largo")); t = T_HEX[m_]
        if familia == "tornillo_hexagonal":
            e, k = esquina(t["s"]), t["k"]
            malla = _union([_hex(e, k, 0), _cil(t["d"], L + 0.2, k - 0.2)])
            rh = e / 2
        else:
            dk, k = T_ALLEN[m_], t["d"]
            malla = _union([_cil(dk, k, 0), _cil(t["d"], L + 0.2, k - 0.2)])
            rh = dk / 2
        cabeza = Cabeza(radio_cabeza=rh, radio_cuerpo=t["d"] / 2, alto_cabeza=k, extremo=-1)
        desc = f"{m_} × {L:g}"
    elif familia == "tuerca_hexagonal":
        m_ = _param(familia, v, "metrica"); t = T_HEX[m_]
        malla = _resta(_hex(esquina(t["s"]), t["m"], 0), _cil(t["d"], t["m"] + 2, -1))
        desc = m_
    elif familia == "tuerca_autofrenante":
        m_ = _param(familia, v, "metrica"); t = T_HEX[m_]; H = T_985[m_]; hb = H * 0.72
        cuerpo = _union([_hex(esquina(t["s"]), hb, 0), _cil(t["s"] * 0.96, H - hb + 0.1, hb - 0.1)])
        malla = _resta(cuerpo, _cil(t["d"], H + 2, -1))
        desc = m_
    elif familia == "arandela_plana":
        m_ = _param(familia, v, "metrica"); d1, d2, h = T_125[m_]
        malla = _anillo(d2, d1, h, 0)
        desc = f"{m_} ({d1:g} × {d2:g} × {h:g})"
    elif familia == "arandela_grower":
        m_ = _param(familia, v, "metrica"); d1, d2, s = T_127[m_]
        malla = _anillo(d2, d1, 1.8 * s, 0)       # alto libre ≈ 1,8 × espesor (resorte abierto)
        vol_override = math.pi * ((d2 / 2) ** 2 - (d1 / 2) ** 2) * s
        desc = m_
    elif familia == "varilla_roscada":
        m_ = _param(familia, v, "metrica"); L = float(_param(familia, v, "largo")); t = T_HEX[m_]
        malla = _cil(t["d"] * 0.92, L, 0)         # diámetro medio de la rosca
        desc = f"{m_} × {L:g}"
    elif familia == "buje":
        D = float(_param(familia, v, "diametro")); di = float(_param(familia, v, "interior")); L = float(_param(familia, v, "largo"))
        if D <= 0 or L <= 0 or di < 0 or di >= D:
            raise ErrorCatalogo("Medidas de buje inválidas: debe cumplirse 0 ≤ interior < exterior y largo > 0.")
        malla = _anillo(D, di, L, 0) if di > 0 else _cil(D, L, 0)
        desc = f"Ø{D:g} × Ø{di:g} × {L:g}"
    elif familia == "rodamiento":
        c = _param(familia, v, "designacion"); d, D, B, kg = T_62[c]
        malla = _anillo(D, d, B, 0)               # envolvente exterior; el peso viene del catálogo
        masa_cat = kg
        desc = f"{c} ({d} × {D} × {B})"

    malla = trimesh.Trimesh(malla.vertices, malla.faces, process=True)
    vol = vol_override or float(abs(malla.volume))
    ext = malla.extents
    redonda = Redonda(eje=2, diametro=float(max(ext[0], ext[1])), largo=float(ext[2]))
    masa = masa_cat if masa_cat else vol * rho / 1000.0
    return Pieza(nombre=f["nombre"], descripcion=desc, origen="catalogo", norma=f["norma"], malla=malla, material=material,
                 masa_kg=masa, origen_masa="catálogo" if masa_cat else "material × volumen",
                 redonda=redonda, cabeza=cabeza, volumen_mm3=vol)


def descripcion_catalogo() -> dict:
    """Catálogo para la interfaz (familias, campos y materiales)."""
    return {"familias": [{"id": k, **f} for k, f in FAMILIAS.items()],
            "materiales": [{"id": k, "nombre": NOMBRES_MATERIAL[k], "densidad_g_cm3": d} for k, d in DENSIDADES.items()]}
