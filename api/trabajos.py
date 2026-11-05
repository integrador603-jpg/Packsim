"""
Trabajos de simulación: ejecución aislada y almacén en memoria con vencimiento.

- Cada simulación corre en un proceso aparte con tiempo y memoria máximos. Si un conversor CAD
  se cuelga o rompe, se mata ese proceso y la API sigue funcionando.
- La memoria se controla midiendo la que el proceso USA (RSS), no la que reserva: las librerías 3D
  reservan mucho espacio de direcciones por cada núcleo del servidor y un límite sobre la reserva
  (RLIMIT_AS) las hacía abortar en servidores con muchos núcleos.
- Los resultados viven solo en memoria y vencen (1 h por defecto). Nada se escribe en disco.
- `Almacen` es una interfaz: para varios servidores se reemplaza por una versión con Redis
  sin tocar el resto de la API.
"""
from __future__ import annotations

import asyncio
import logging
import multiprocessing as mp
import os
import signal
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("packsim.trabajos")

_ctx = mp.get_context("forkserver")
_ctx.set_forkserver_preload(["api.tarea"])      # las librerías pesadas se cargan una sola vez


@dataclass
class Trabajo:
    id: str
    estado: str = "en_cola"                     # en_cola | procesando | listo | error
    creado: float = field(default_factory=time.time)
    terminado: Optional[float] = None
    resultado: Optional[dict] = None
    advertencias: list = field(default_factory=list)
    glb: Optional[bytes] = None
    error: Optional[str] = None
    duracion_ms: Optional[int] = None

    def publico(self, con_resultado: bool = True) -> dict:
        d = {"id": self.id, "estado": self.estado, "duracion_ms": self.duracion_ms}
        if self.estado == "listo":
            d["advertencias"] = self.advertencias
            d["malla_visor"] = f"/v1/trabajos/{self.id}/malla"
            if con_resultado:
                d["resultado"] = self.resultado
        if self.estado == "error":
            d["error"] = self.error
        return d


class Almacen:
    """Almacén en memoria con vencimiento y tope de cantidad."""

    def __init__(self, vencimiento_s: int, maximo: int):
        self.vencimiento_s, self.maximo = vencimiento_s, maximo
        self._t: dict[str, Trabajo] = {}
        self._lock = threading.Lock()

    def nuevo(self) -> Trabajo:
        with self._lock:
            self._purgar()
            if len(self._t) >= self.maximo:
                raise OverflowError("Hay demasiadas simulaciones en curso. Probá de nuevo en unos minutos.")
            t = Trabajo(id=uuid.uuid4().hex)
            self._t[t.id] = t
            return t

    def obtener(self, id_: str) -> Optional[Trabajo]:
        with self._lock:
            self._purgar()
            return self._t.get(id_)

    def borrar(self, id_: str) -> bool:
        with self._lock:
            return self._t.pop(id_, None) is not None

    def _purgar(self):
        ahora = time.time()
        for k in [k for k, t in self._t.items() if t.terminado and ahora - t.terminado > self.vencimiento_s]:
            del self._t[k]

    def __len__(self):
        with self._lock:
            return len(self._t)


def _hijo(conn, params, datos, nombre, memoria_mb):
    try:
        from api.tarea import correr
        conn.send(correr(params, datos, nombre))
    except MemoryError:
        conn.send({"ok": False, "error": "La pieza necesita más memoria de la permitida. Exportala con menos detalle.", "tipo": "limite"})
    except BaseException:
        log.exception("Error interno en la simulación")
        conn.send({"ok": False, "error": "Error interno al simular. Si se repite, avisá con el código del trabajo.", "tipo": "interno"})
    finally:
        conn.close()


def memoria_usada_mb(pid: int) -> float:
    """Memoria residente (RSS) del proceso y sus hijos directos (p. ej. el conversor de DWG)."""
    total = 0.0
    pids = [pid]
    try:
        with open(f"/proc/{pid}/task/{pid}/children") as fh:
            pids += [int(x) for x in fh.read().split()]
    except OSError:
        pass
    for q in pids:
        try:
            with open(f"/proc/{q}/status") as fh:
                for linea in fh:
                    if linea.startswith("VmRSS:"):
                        total += int(linea.split()[1]) / 1024
                        break
        except OSError:
            pass
    return total


def _motivo_salida(codigo: Optional[int]) -> tuple[str, str]:
    if codigo == -signal.SIGKILL:
        return ("El servidor se quedó sin memoria con esta pieza. Exportala con menos detalle o probá de nuevo.", "memoria")
    if codigo in (-signal.SIGSEGV, -signal.SIGABRT, -signal.SIGBUS):
        return ("El lector 3D falló con este archivo. Probá exportarlo de nuevo, idealmente como STEP.", "lector")
    return ("El proceso de simulación terminó de forma inesperada. Probá de nuevo; si se repite, el archivo puede estar dañado.", "interno")


def ejecutar_aislado(params: dict, datos: Optional[bytes], nombre: Optional[str], tiempo_max_s: int, memoria_mb: int,
                     destino=_hijo, intervalo_s: float = 0.2) -> dict:
    """Corre `destino` en otro proceso y lo vigila: lo corta si supera el tiempo o la memoria. Bloqueante."""
    rx, tx = _ctx.Pipe(duplex=False)
    p = _ctx.Process(target=destino, args=(tx, params, datos, nombre, memoria_mb), daemon=True)
    p.start()
    tx.close()
    fin = time.monotonic() + tiempo_max_s
    pico = 0.0
    try:
        while True:
            if rx.poll(intervalo_s):
                try:
                    return rx.recv()
                except EOFError:
                    p.join(5)
                    msg, tipo = _motivo_salida(p.exitcode)
                    log.warning("proceso terminado sin respuesta: codigo=%s motivo=%s pico_mb=%.0f", p.exitcode, tipo, pico)
                    return {"ok": False, "error": msg, "tipo": tipo}
            uso = memoria_usada_mb(p.pid)
            pico = max(pico, uso)
            if uso > memoria_mb:
                log.warning("proceso cortado por memoria: uso_mb=%.0f limite_mb=%s", uso, memoria_mb)
                return {"ok": False, "error": f"La pieza necesitó más de {memoria_mb} MB de memoria y se canceló. Exportala con menos detalle.", "tipo": "limite"}
            if time.monotonic() > fin:
                return {"ok": False, "error": f"La simulación superó el tiempo máximo de {tiempo_max_s} s y se canceló.", "tipo": "limite"}
            if not p.is_alive() and not rx.poll(0):
                p.join(5)
                msg, tipo = _motivo_salida(p.exitcode)
                log.warning("proceso terminado sin respuesta: codigo=%s motivo=%s pico_mb=%.0f", p.exitcode, tipo, pico)
                return {"ok": False, "error": msg, "tipo": tipo}
    finally:
        rx.close()
        if p.is_alive():
            p.kill()
        p.join(5)


class Ejecutor:
    def __init__(self, almacen: Almacen, paralelos: int, tiempo_max_s: int, memoria_mb: int):
        self.almacen, self.tiempo_max_s, self.memoria_mb = almacen, tiempo_max_s, memoria_mb
        self._sem = asyncio.Semaphore(paralelos)

    async def correr(self, t: Trabajo, params: dict, datos: Optional[bytes], nombre: Optional[str], huella: str):
        async with self._sem:
            t.estado = "procesando"
            t0 = time.perf_counter()
            r = await asyncio.to_thread(ejecutar_aislado, params, datos, nombre, self.tiempo_max_s, self.memoria_mb)
            del datos                                      # los bytes del archivo dejan de existir acá
            t.duracion_ms = round((time.perf_counter() - t0) * 1000)
            if r.get("ok"):
                t.resultado, t.advertencias, t.glb, t.estado = r["resultado"], r["advertencias"], r["glb"], "listo"
            else:
                t.error, t.estado = r["error"], "error"
            t.terminado = time.time()
            # en los logs solo la huella del archivo, nunca su nombre ni contenido
            log.info("trabajo=%s huella=%s estado=%s ms=%s tipo=%s", t.id[:8], huella, t.estado, t.duracion_ms, r.get("tipo", "-"))
