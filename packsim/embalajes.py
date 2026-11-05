"""Catálogo de embalajes de referencia y estimación de tara."""
from __future__ import annotations

# espesor de pared (mm), fricción para la física, kg por m² de superficie (para estimar la tara)
TIPOS = {
    "carton": {"nombre": "Cartón corrugado", "espesor_mm": 5, "friccion": 0.45, "kg_m2": 0.7},
    "madera": {"nombre": "Madera", "espesor_mm": 18, "friccion": 0.5, "kg_m2": 8.6},
    "plastico": {"nombre": "Plástico", "espesor_mm": 4, "friccion": 0.3, "kg_m2": 3.2},
}

# medidas interiores (mm), carga máxima (kg), tipo, tara de referencia (kg)
CATALOGO = [
    {"id": "minuteria_chica", "nombre": "Caja de minutería chica", "interior_mm": [200, 150, 100], "carga_max_kg": 10, "tipo": "carton", "tara_kg": 0.15},
    {"id": "minuteria", "nombre": "Caja de minutería", "interior_mm": [300, 200, 150], "carga_max_kg": 15, "tipo": "carton", "tara_kg": 0.3},
    {"id": "carton_mediana", "nombre": "Caja de cartón mediana", "interior_mm": [400, 300, 200], "carga_max_kg": 20, "tipo": "carton", "tara_kg": 0.55},
    {"id": "carton_grande", "nombre": "Caja de cartón grande", "interior_mm": [600, 400, 300], "carga_max_kg": 30, "tipo": "carton", "tara_kg": 1.1},
    {"id": "plastico_apilable", "nombre": "Cajón plástico apilable", "interior_mm": [560, 360, 260], "carga_max_kg": 40, "tipo": "plastico", "tara_kg": 2.2},
    {"id": "madera", "nombre": "Cajón de madera", "interior_mm": [800, 600, 500], "carga_max_kg": 250, "tipo": "madera", "tara_kg": 22},
    {"id": "madera_pallet", "nombre": "Cajón de madera tipo pallet", "interior_mm": [1150, 750, 600], "carga_max_kg": 600, "tipo": "madera", "tara_kg": 38},
]


def estimar_tara(interior_mm, tipo: str) -> float:
    """Tara aproximada: superficie exterior × peso por m² del material (+12% de patines en madera)."""
    if tipo not in TIPOS:
        raise ValueError(f"Tipo de embalaje desconocido: {tipo}")
    t = TIPOS[tipo]
    e = t["espesor_mm"]
    L, W, H = [(x + 2 * e) / 1000 for x in interior_mm[:2]] + [(interior_mm[2] + e) / 1000]
    area = 2 * (L * W + L * H + W * H)
    if tipo == "carton":
        area = 2 * (L * H + W * H) + 2 * (L * W + W * W)   # caja RSC: las solapas cubren L·W + W² arriba y abajo
    if tipo == "plastico":
        area -= L * W                 # sin tapa
    kg = area * t["kg_m2"]
    if tipo == "madera":
        kg *= 1.12
    return round(kg * 20) / 20
