"""
Punto de entrada del motor: simular(pieza, embalaje, criterios) → resultado (contrato v1).

Saturación = piezas que van ÷ máximo de piezas que físicamente entran (capacidad).
El peso no es saturación: es un límite que se informa aparte.
"""
from __future__ import annotations

import math
import time
from collections import Counter

from . import __version__
from .empaque import EJES, elegir, evaluar, fraccion_apoyada
from .modelos import VERSION_CONTRATO, Criterios, Embalaje, Pieza


class ErrorSimulacion(ValueError):
    pass


def resumen_pesos(pieza: Pieza, emb: Embalaje, crit: Criterios, n_max: int) -> dict:
    """Límite por peso, cantidad recomendada, saturación y peso bruto."""
    tara, relleno = max(0.0, emb.tara_kg), max(0.0, emb.relleno_kg)
    manual = crit.peso_bruto_manipulable_kg if crit.manipulacion == "manual" and crit.peso_bruto_manipulable_kg > 0 else 0.0
    limites = []
    if emb.carga_max_kg > 0:
        limites.append((emb.carga_max_kg, "carga máxima del embalaje"))
    if manual:
        limites.append((manual - tara - relleno, "peso bruto manipulable"))   # lo que queda para piezas
    lim_kg, lim_origen = min(limites, key=lambda x: x[0]) if limites else (math.inf, None)
    lim_kg = max(0.0, lim_kg)
    n_peso = math.floor(lim_kg / pieza.masa_kg + 1e-9) if math.isfinite(lim_kg) else None
    n = min(n_max, n_peso) if n_peso is not None else n_max
    auditoria = crit.piezas_actuales if crit.piezas_actuales > 0 else 0
    n_mostrado = auditoria or n
    peso_piezas = n_mostrado * pieza.masa_kg
    limitado_peso = n_peso is not None and n_peso < n_max
    return {
        "piezas": n_mostrado,
        "piezas_recomendadas": n,
        "maximo_posible": n_max,
        "saturacion": round(n_mostrado / n_max, 4) if n_max else 0.0,
        "limitado_por": lim_origen if limitado_peso else "espacio",
        "limite_por_peso": n_peso,
        "embalaje_vacio_excede_limite_manual": bool(manual and tara + relleno >= manual),
        "auditoria": bool(auditoria),
        "piezas_que_faltan": max(0, n - auditoria) if auditoria else 0,
        "peso_piezas_kg": round(peso_piezas, 4),
        "peso_bruto_kg": round(peso_piezas + tara + relleno, 4),
        "peso_bruto_detalle_kg": {"piezas": round(peso_piezas, 4), "embalaje": tara, "relleno": relleno},
        "volumen_ocupado": round(n_mostrado * pieza.volumen_mm3 / emb.volumen_mm3, 4),
    }


def _explicacion(mejor, grilla, alts, prioridad, pesos, pieza) -> str:
    if mejor is None:
        return "La pieza no entra en el embalaje en ninguna orientación permitida."
    partes = [f"Se evaluaron {len(alts)} estrategias. Gana {mejor.nombre} con {mejor.piezas} piezas"]
    if grilla and grilla.piezas and mejor.id != "grilla":
        partes[0] += f", {mejor.piezas - grilla.piezas} más que la grilla simple (+{round((mejor.piezas / grilla.piezas - 1) * 100)}%)"
    partes[0] += "."
    if mejor.id == "cabeza_cola":
        partes.append("Alternar cabeza y punta deja la cabeza de cada pieza junto al cuerpo de su vecina.")
    elif mejor.id == "tresbolillo":
        partes.append("Las piezas redondas en filas intercaladas aprovechan el hueco que deja cada círculo.")
    elif mejor.id == "mixtos":
        partes.append(f"Combina {mejor.orientaciones} orientaciones para rellenar el espacio que una sola deja vacío.")
    if prioridad == "picking":
        partes.append("Por prioridad de picking se eligió la opción con menos orientaciones dentro del 5% del máximo.")
    elif prioridad == "estabilidad":
        partes.append("Por prioridad de estabilidad se eligió la opción con más piezas apoyadas en su cara grande dentro del 5% del máximo.")
    if pesos["embalaje_vacio_excede_limite_manual"]:
        partes.append("El embalaje vacío ya pesa igual o más que el límite manual: hace falta autoelevador o un embalaje más liviano.")
    elif pesos["limitado_por"] != "espacio":
        partes.append(f"El peso manda: {mejor.piezas} piezas pesarían {mejor.piezas * pieza.masa_kg:.1f} kg; "
                      f"por {'el' if pesos['limitado_por'].startswith('peso') else 'la'} {pesos['limitado_por']} entran {pesos['limite_por_peso']}.")
    return " ".join(partes)


def _capas(alt) -> list[dict]:
    if not alt:
        return []
    cnt = Counter(round(float(c.centro_mm[2]), 2) for c in alt.colocaciones)
    return [{"nivel": i + 1, "altura_centro_mm": z, "piezas": cnt[z]} for i, z in enumerate(sorted(cnt))]


def info_pieza(pieza: Pieza) -> dict:
    """Ficha de la pieza para mostrar (sin geometría)."""
    return {
        "nombre": f"{pieza.nombre} {pieza.descripcion}" if pieza.origen == "catalogo" else pieza.nombre,
        "origen": pieza.origen,
        "norma_o_archivo": pieza.norma,
        "envolvente_mm": [round(float(x), 3) for x in pieza.envolvente_mm],
        "centro_envolvente_mm": [round(float(x), 3) for x in pieza.centro_mm],
        "volumen_cm3": round(pieza.volumen_mm3 / 1000, 4),
        "peso_kg": round(pieza.masa_kg, 5),
        "origen_peso": pieza.origen_masa,
        "material": pieza.material,
        "solido_cerrado": bool(pieza.malla.is_watertight),
    }


def _friccion(emb: Embalaje) -> float:
    from .embalajes import TIPOS
    return TIPOS.get(emb.tipo, {}).get("friccion", 0.45)


def _alternativas(alts, pieza):
    return [{"id": a.id, "nombre": a.nombre, "detalle": a.detalle, "piezas": a.piezas,
             "orientaciones": a.orientaciones, "apoyadas_en_cara_grande": round(fraccion_apoyada(a, pieza), 3)}
            for a in sorted(alts, key=lambda a: -a.piezas)]


def simular(pieza: Pieza, emb: Embalaje, crit: Criterios, incluir_disposicion: bool = True,
            max_disposicion: int = 20_000, avisar=None) -> dict:
    """
    Calcula el resultado (contrato v1). En modo granel o con `crit.validar_fisica` corre la simulación
    física; la animación queda en la clave interna "_animacion" (bytes, no forma parte del contrato).
    """
    t0 = time.perf_counter()
    B = [float(x) for x in emb.interior_mm]
    if min(B) <= 0:
        raise ErrorSimulacion("Las medidas interiores del embalaje deben ser positivas.")
    if pieza.masa_kg <= 0:
        raise ErrorSimulacion("El peso de la pieza debe ser mayor que cero.")

    alts = evaluar(B, pieza, max(0.0, crit.holgura_mm), crit.mantener_posicion)
    mejor = elegir(alts, pieza, crit.prioridad)
    animacion = None
    if crit.modo == "granel":
        return _simular_granel(pieza, emb, crit, alts, mejor, t0, avisar)
    n_max = mejor.piezas if mejor else 0
    pesos = resumen_pesos(pieza, emb, crit, n_max)
    grilla = next((a for a in alts if a.id == "grilla"), None)
    fisica = None
    if crit.validar_fisica and mejor and pesos["piezas"]:
        from .fisica import ErrorFisica, validar
        try:
            fisica = validar(pieza, emb, mejor.colocaciones[:pesos["piezas"]], _friccion(emb), avisar)
            animacion = fisica.pop("animacion")
            fisica["tipo"] = "validacion"
        except ErrorFisica as e:
            fisica = {"tipo": "validacion", "error": str(e)}

    salida = {
        "version": VERSION_CONTRATO,
        "motor": f"packsim {__version__}",
        "tiempo_ms": round((time.perf_counter() - t0) * 1000),
        "pieza": info_pieza(pieza),
        "embalaje": {"nombre": emb.nombre, "tipo": emb.tipo, "interior_mm": list(emb.interior_mm),
                     "carga_max_kg": emb.carga_max_kg or None, "tara_kg": emb.tara_kg, "relleno_kg": emb.relleno_kg},
        "criterios": {"modo": crit.modo, "holgura_mm": crit.holgura_mm, "manipulacion": crit.manipulacion,
                      "peso_bruto_manipulable_kg": crit.peso_bruto_manipulable_kg if crit.manipulacion == "manual" else None,
                      "mantener_posicion": crit.mantener_posicion, "prioridad": crit.prioridad,
                      "piezas_actuales": crit.piezas_actuales or None},
        "resultado": {
            "estrategia": mejor.nombre if mejor else None,
            "estrategia_id": mejor.id if mejor else None,
            **pesos,
            "explicacion": _explicacion(mejor, grilla, alts, crit.prioridad, pesos, pieza),
            "alternativas": _alternativas(alts, pieza),
            "capas": _capas(mejor),
            "disposicion": [c.a_dict() for c in mejor.colocaciones[:max_disposicion]] if (mejor and incluir_disposicion) else [],
            "nota_disposicion": "Marco del embalaje: origen en la esquina interior inferior; x largo, y ancho, z alto. "
                                "p_embalaje = rotacion · (p_pieza − centro_envolvente_mm) + centro_mm. "
                                "La disposición está ordenada de abajo hacia arriba: las primeras `piezas` son las que van.",
            "fisica": fisica,
        },
    }
    if animacion:
        salida["_animacion"] = animacion
    return salida


def _encabezado(pieza, emb, crit, t0):
    return {
        "version": VERSION_CONTRATO,
        "motor": f"packsim {__version__}",
        "tiempo_ms": round((time.perf_counter() - t0) * 1000),
        "pieza": info_pieza(pieza),
        "embalaje": {"nombre": emb.nombre, "tipo": emb.tipo, "interior_mm": list(emb.interior_mm),
                     "carga_max_kg": emb.carga_max_kg or None, "tara_kg": emb.tara_kg, "relleno_kg": emb.relleno_kg},
        "criterios": {"modo": crit.modo, "holgura_mm": crit.holgura_mm, "manipulacion": crit.manipulacion,
                      "peso_bruto_manipulable_kg": crit.peso_bruto_manipulable_kg if crit.manipulacion == "manual" else None,
                      "mantener_posicion": crit.mantener_posicion, "prioridad": crit.prioridad,
                      "piezas_actuales": crit.piezas_actuales or None},
    }


def _simular_granel(pieza, emb, crit, alts, mejor, t0, avisar):
    """El 100% a granel es lo que entra volcando y vibrando (simulación física)."""
    from .fisica import ErrorFisica, granel
    try:
        fis = granel(pieza, emb, _friccion(emb), avisar)
    except ErrorFisica as e:
        raise ErrorSimulacion(str(e))
    animacion = fis.pop("animacion")
    disposicion = fis.pop("disposicion")
    n = fis["piezas_que_entran"]
    max_ord = mejor.piezas if mejor else 0
    fis["acotado_al_ordenado"] = bool(max_ord and n > max_ord)      # a granel no puede entrar más que acomodado
    if fis["acotado_al_ordenado"]:
        n = max_ord
    fis["maximo_ordenado"] = max_ord
    fis["tipo"] = "granel"
    pesos = resumen_pesos(pieza, emb, crit, n)
    partes = [f"Volcando piezas con orientación al azar y vibrando el embalaje entran {n}."]
    if fis["extrapolado"]:
        m = fis["muestra"]
        partes.append(f"Se simuló una muestra de {' × '.join(f'{x:g}' for x in m['interior_mm'])} mm ({m['piezas']} piezas) "
                      "y se extrapoló al embalaje completo con la densidad del interior y la corrección por bordes (±5%).")
    if max_ord:
        partes.append(f"Acomodadas en orden entrarían {max_ord}" + (f" ({round((max_ord / n - 1) * 100)}% más)." if n and max_ord > n else "."))
    if fis["acotado_al_ordenado"]:
        partes.append("El conteo a granel superaba al ordenado y se acotó a ese valor.")
    if pesos["limitado_por"] != "espacio":
        partes.append(f"Por {'el' if pesos['limitado_por'].startswith('peso') else 'la'} {pesos['limitado_por']} van {pesos['limite_por_peso']}.")
    salida = {
        **_encabezado(pieza, emb, crit, t0),
        "resultado": {
            "estrategia": "A granel",
            "estrategia_id": "granel",
            **pesos,
            "explicacion": " ".join(partes),
            "alternativas": [{"id": "granel", "nombre": "A granel", "detalle": "volcado y vibrado simulado", "piezas": n,
                              "orientaciones": 0, "apoyadas_en_cara_grande": None}] + _alternativas(alts, pieza),
            "capas": [],
            # si se simuló una muestra, las posiciones son de la muestra: no se dibujan en el embalaje completo
            "disposicion": [] if fis["extrapolado"] else disposicion,
            "nota_disposicion": "A granel la rotación no es de enteros. Si el resultado es extrapolado, ver fisica.interior_simulado_mm.",
            "fisica": fis,
        },
        "_animacion": animacion,
    }
    return salida
