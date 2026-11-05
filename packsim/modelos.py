"""
Modelos de datos y contrato de salida v1.

Convenciones (válidas en todo el paquete):
- Unidades: milímetros y kilogramos.
- Marco del embalaje: origen en la esquina interior inferior; x = largo, y = ancho, z = alto.
- Colocación de una pieza: p_embalaje = R · (p_pieza − c_pieza) + centro
  donde p_pieza son coordenadas del archivo o del catálogo, c_pieza el centro de su caja
  envolvente (Pieza.centro_mm), R una matriz de rotación 3×3 de enteros (−1, 0, 1)
  y centro la posición en el embalaje.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import trimesh

VERSION_CONTRATO = "1.0"


@dataclass
class Redonda:
    """Pieza de revolución alrededor de un eje de su caja envolvente."""
    eje: int          # 0, 1 o 2 (x, y, z del sistema de la pieza)
    diametro: float   # mm, diámetro de la envolvente cilíndrica
    largo: float      # mm, a lo largo del eje


@dataclass
class Cabeza:
    """Pieza con cabeza más ancha que el cuerpo (tornillos): permite cabeza-cola."""
    radio_cabeza: float   # mm (radio circunscripto)
    radio_cuerpo: float   # mm
    alto_cabeza: float    # mm
    extremo: int          # +1 si la cabeza está del lado positivo del eje, −1 si del negativo


@dataclass
class Pieza:
    nombre: str
    malla: trimesh.Trimesh            # mm, coordenadas originales
    masa_kg: float
    origen_masa: str                  # "catálogo" | "material × volumen" | "cargada"
    descripcion: str = ""
    norma: str = ""
    material: str = "acero"
    origen: str = "archivo"           # "catalogo" | "archivo"
    redonda: Optional[Redonda] = None
    cabeza: Optional[Cabeza] = None
    volumen_mm3: float = 0.0

    def __post_init__(self):
        if not self.volumen_mm3:
            self.volumen_mm3 = volumen_seguro(self.malla)

    @property
    def envolvente_mm(self) -> np.ndarray:
        return np.asarray(self.malla.extents, dtype=float)

    @property
    def centro_mm(self) -> np.ndarray:
        return np.asarray(self.malla.bounds.mean(axis=0), dtype=float)


def volumen_seguro(m: trimesh.Trimesh) -> float:
    """Volumen exacto si la malla es cerrada; si no, el de su envolvente convexa (cota superior)."""
    if m.is_watertight:
        return float(abs(m.volume))
    try:
        return float(m.convex_hull.volume)
    except Exception:
        return float(np.prod(m.extents))


@dataclass
class Embalaje:
    interior_mm: tuple                # (largo, ancho, alto)
    tipo: str = "carton"              # carton | madera | plastico
    nombre: str = "A medida"
    carga_max_kg: float = 0.0         # 0 = sin límite
    tara_kg: float = 0.0
    relleno_kg: float = 0.0

    @property
    def volumen_mm3(self) -> float:
        L, W, H = self.interior_mm
        return float(L * W * H)


@dataclass
class Criterios:
    modo: str = "ordenado"            # ordenado | granel
    holgura_mm: float = 1.0
    manipulacion: str = "manual"      # manual | autoelevador
    peso_bruto_manipulable_kg: float = 15.0
    mantener_posicion: bool = False   # True: no acostar ni invertir la pieza
    prioridad: str = "cantidad"       # cantidad | estabilidad | picking
    piezas_actuales: int = 0          # auditoría (0 = no aplica)


@dataclass
class Colocacion:
    centro_mm: np.ndarray             # (3,)
    rotacion: np.ndarray              # (3, 3) enteros
    clave: str                        # identifica la orientación (para colores/picking)

    def a_dict(self):
        return {"centro_mm": [round(float(v), 3) for v in self.centro_mm],
                "rotacion": self.rotacion.astype(int).tolist()}


@dataclass
class Alternativa:
    id: str
    nombre: str
    detalle: str
    colocaciones: list = field(default_factory=list)

    @property
    def piezas(self) -> int:
        return len(self.colocaciones)

    @property
    def orientaciones(self) -> int:
        return len({c.clave for c in self.colocaciones})
