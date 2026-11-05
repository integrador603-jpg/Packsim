"""Validación de los parámetros de una simulación."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class PiezaIn(BaseModel):
    origen: Literal["catalogo", "archivo"]
    familia: Optional[str] = None
    valores: dict = Field(default_factory=dict)
    material: str = "acero"
    unidades: Literal["mm", "cm", "m", "in"] = "mm"
    peso_kg: Optional[float] = Field(default=None, gt=0, le=10_000)
    nombre: Optional[str] = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def _familia(self):
        if self.origen == "catalogo" and not self.familia:
            raise ValueError("Falta la familia del catálogo.")
        return self


class EmbalajeIn(BaseModel):
    interior_mm: list[float] = Field(min_length=3, max_length=3)
    tipo: Literal["carton", "madera", "plastico"] = "carton"
    nombre: str = Field(default="A medida", max_length=120)
    carga_max_kg: float = Field(default=0, ge=0, le=100_000)
    tara_kg: float = Field(default=0, ge=0, le=10_000)
    relleno_kg: float = Field(default=0, ge=0, le=10_000)

    @model_validator(mode="after")
    def _medidas(self):
        if any(x <= 0 or x > 20_000 for x in self.interior_mm):
            raise ValueError("Las medidas interiores deben estar entre 0 y 20.000 mm.")
        return self


class CriteriosIn(BaseModel):
    modo: Literal["ordenado", "granel"] = "ordenado"
    holgura_mm: float = Field(default=1.0, ge=0, le=100)
    manipulacion: Literal["manual", "autoelevador"] = "manual"
    peso_bruto_manipulable_kg: float = Field(default=15, ge=0, le=10_000)
    mantener_posicion: bool = False
    prioridad: Literal["cantidad", "estabilidad", "picking"] = "cantidad"
    piezas_actuales: int = Field(default=0, ge=0, le=10_000_000)
    validar_fisica: bool = False


class ParametrosIn(BaseModel):
    pieza: PiezaIn
    embalaje: EmbalajeIn
    criterios: CriteriosIn = Field(default_factory=CriteriosIn)


class PiezaSolaIn(BaseModel):
    pieza: PiezaIn


class SesionIn(BaseModel):
    clave: str = Field(max_length=200)
