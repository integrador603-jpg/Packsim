"""
API de Packsim (sin estado).

  POST   /v1/sesion                 inicia sesión con la contraseña (cookie firmada)
  GET    /v1/catalogo               piezas, materiales y embalajes de referencia
  GET    /v1/embalajes/tara         tara estimada de un embalaje a medida
  POST   /v1/simulaciones           crea una simulación (archivo 3D o pieza del catálogo)
  POST   /v1/piezas                 analiza solo la pieza (ficha y malla para la vista previa)
  GET    /v1/trabajos/{id}          estado y resultado de una simulación o análisis
  GET    /v1/trabajos/{id}/malla    pieza liviana en GLB para el visor
  DELETE /v1/trabajos/{id}          borra el resultado antes de que venza
  (/v1/simulaciones/{id} sigue disponible como alias)

Nada se guarda en disco. Los resultados viven en memoria y vencen solos.
Correr local:  uvicorn api.app:app --reload
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from packsim import __version__
from packsim.catalogo import descripcion_catalogo
from packsim.embalajes import CATALOGO, TIPOS, estimar_tara
from packsim.lectura import FORMATOS

from .config import Config
from .esquemas import ParametrosIn, PiezaSolaIn, SesionIn
from .seguridad import COOKIE, LimiteFrecuencia, clave_correcta, crear_token, exigir_acceso, ip_cliente, token_valido
from .trabajos import Almacen, Ejecutor, ejecutar_aislado

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("packsim.api")
WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


def crear_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or Config()
    app = FastAPI(title="Packsim", version=__version__, docs_url="/docs" if cfg.abierta else None, redoc_url=None)
    app.state.cfg = cfg
    app.state.almacen = Almacen(cfg.vencimiento_s, cfg.trabajos_max_en_memoria)
    app.state.limite = LimiteFrecuencia(cfg.limite_por_hora)
    app.state.tareas = set()
    app.state.ejecutor = None
    if cfg.abierta:
        log.warning("PACKSIM_CLAVE no está configurada: la API queda abierta (solo para uso local).")

    def ejecutor() -> Ejecutor:
        if app.state.ejecutor is None:
            app.state.ejecutor = Ejecutor(app.state.almacen, cfg.trabajos_paralelos, cfg.tiempo_max_s, cfg.memoria_max_mb,
                                          cfg.tiempo_max_fisica_s)
        return app.state.ejecutor

    # ───────────── cabeceras y errores ─────────────
    @app.middleware("http")
    async def cabeceras(request: Request, call_next):
        r = await call_next(request)
        r.headers["X-Content-Type-Options"] = "nosniff"
        r.headers["X-Frame-Options"] = "DENY"
        r.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/v1"):
            r.headers["Cache-Control"] = "no-store"
        else:
            r.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
                "img-src 'self' data: blob:; connect-src 'self' blob: data:; worker-src 'self' blob:; frame-ancestors 'none'")
        return r

    @app.exception_handler(HTTPException)
    async def _http(_, exc: HTTPException):
        return JSONResponse({"detalle": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _val(_, exc: RequestValidationError):
        return JSONResponse({"detalle": "Parámetros inválidos.", "errores": [_msg(e) for e in exc.errors()]}, status_code=422)

    # ───────────── sesión ─────────────
    @app.get("/salud")
    def salud():
        return {"estado": "ok", "version": __version__}

    @app.get("/v1/sesion")
    def ver_sesion(request: Request):
        return {"requiere_clave": not cfg.abierta, "activa": cfg.abierta or token_valido(cfg.secreto, request.cookies.get(COOKIE))}

    @app.post("/v1/sesion")
    async def iniciar_sesion(datos: SesionIn, request: Request, response: Response):
        if cfg.abierta:
            return {"activa": True}
        if not app.state.limite.permitir("login:" + ip_cliente(request)):
            raise HTTPException(429, "Demasiados intentos. Esperá un rato.")
        if not clave_correcta(cfg.clave, datos.clave):
            await asyncio.sleep(0.6)                        # frena intentos por fuerza bruta
            raise HTTPException(401, "Contraseña incorrecta.")
        response.set_cookie(COOKIE, crear_token(cfg.secreto, cfg.sesion_horas), max_age=cfg.sesion_horas * 3600,
                            httponly=True, samesite="strict", secure=cfg.cookies_seguras, path="/")
        return {"activa": True}

    @app.delete("/v1/sesion")
    def cerrar_sesion(response: Response):
        response.delete_cookie(COOKIE, path="/")
        return {"activa": False}

    @app.get("/v1/diagnostico", dependencies=[Depends(exigir_acceso)])
    async def diagnostico():
        """Prueba el motor dentro del servidor (útil después de cada despliegue)."""
        import shutil
        prueba = {"pieza": {"origen": "catalogo", "familia": "tornillo_hexagonal", "valores": {"metrica": "M10", "largo": 50}},
                  "embalaje": {"interior_mm": [300, 200, 150]}, "criterios": {}}
        t0 = time.perf_counter()
        r = await asyncio.to_thread(ejecutar_aislado, prueba, None, None, cfg.tiempo_max_s, cfg.memoria_max_mb)
        return {
            "motor_ok": bool(r.get("ok")) and r["resultado"]["resultado"]["maximo_posible"] > 0,
            "error": r.get("error"),
            "prueba_ms": round((time.perf_counter() - t0) * 1000),
            "nucleos": os.cpu_count(),
            "memoria_contenedor_mb": _memoria_contenedor_mb(),
            "limite_por_simulacion_mb": cfg.memoria_max_mb,
            "conversor_dwg": bool(os.environ.get("PACKSIM_DWG2DXF") or shutil.which("dwg2dxf")),
            "version": __version__,
        }

    # ───────────── catálogo ─────────────
    @app.get("/v1/catalogo", dependencies=[Depends(exigir_acceso)])
    def catalogo():
        return {**descripcion_catalogo(), "embalajes": CATALOGO, "tipos_embalaje": TIPOS, "formatos": list(FORMATOS),
                "tamano_max_mb": cfg.tamano_max_mb}

    @app.get("/v1/embalajes/tara", dependencies=[Depends(exigir_acceso)])
    def tara(largo: float, ancho: float, alto: float, tipo: str = "carton"):
        if min(largo, ancho, alto) <= 0:
            raise HTTPException(422, "Las medidas deben ser positivas.")
        try:
            return {"tara_kg": estimar_tara((largo, ancho, alto), tipo), "estimada": True}
        except ValueError as e:
            raise HTTPException(422, str(e))

    # ───────────── simulaciones ─────────────
    async def _encolar(request, modelo, parametros, archivo):
        if not app.state.limite.permitir(ip_cliente(request)):
            raise HTTPException(429, "Llegaste al máximo de simulaciones por hora. Probá más tarde.")
        try:
            p = modelo.model_validate(json.loads(parametros))
        except (json.JSONDecodeError, ValidationError) as e:
            errores = [_msg(x) for x in e.errors()] if isinstance(e, ValidationError) else ["El campo 'parametros' no es JSON válido."]
            raise HTTPException(422, "Parámetros inválidos: " + "; ".join(errores))

        datos, nombre, huella = None, None, "catalogo"
        if p.pieza.origen == "archivo":
            if archivo is None or not archivo.filename:
                raise HTTPException(422, "Falta el archivo 3D de la pieza.")
            nombre = os.path.basename(archivo.filename)
            ext = nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""
            if ext not in FORMATOS:
                raise HTTPException(415, f"Formato no soportado (.{ext}). Usá STEP, IGES, STL, OBJ, GLB, DXF o DWG.")
            datos = await _leer_limitado(archivo, cfg.tamano_max_mb)
            huella = hashlib.sha256(datos).hexdigest()[:12]
            nombre = "pieza." + ext                     # el nombre original no sale de acá

        try:
            t = app.state.almacen.nuevo()
        except OverflowError as e:
            raise HTTPException(503, str(e))
        tarea = asyncio.create_task(ejecutor().correr(t, p.model_dump(), datos, nombre, huella))
        app.state.tareas.add(tarea)
        tarea.add_done_callback(app.state.tareas.discard)
        return {"id": t.id, "estado": t.estado, "consultar": f"/v1/trabajos/{t.id}"}

    @app.post("/v1/simulaciones", status_code=202, dependencies=[Depends(exigir_acceso)])
    async def crear_simulacion(request: Request, parametros: str = Form(...), archivo: UploadFile | None = File(None)):
        return await _encolar(request, ParametrosIn, parametros, archivo)

    @app.post("/v1/piezas", status_code=202, dependencies=[Depends(exigir_acceso)])
    async def analizar_pieza(request: Request, parametros: str = Form(...), archivo: UploadFile | None = File(None)):
        return await _encolar(request, PiezaSolaIn, parametros, archivo)

    @app.get("/v1/trabajos/{id_}", dependencies=[Depends(exigir_acceso)])
    @app.get("/v1/simulaciones/{id_}", dependencies=[Depends(exigir_acceso)], include_in_schema=False)
    def ver_simulacion(id_: str):
        t = app.state.almacen.obtener(id_)
        if not t:
            raise HTTPException(404, "La simulación no existe o ya venció (los resultados duran una hora).")
        return t.publico()

    @app.get("/v1/trabajos/{id_}/malla", dependencies=[Depends(exigir_acceso)])
    @app.get("/v1/simulaciones/{id_}/malla", dependencies=[Depends(exigir_acceso)], include_in_schema=False)
    def malla(id_: str):
        t = app.state.almacen.obtener(id_)
        if not t or t.estado != "listo" or not t.glb:
            raise HTTPException(404, "La malla no está disponible.")
        return Response(t.glb, media_type="model/gltf-binary")

    @app.get("/v1/trabajos/{id_}/animacion", dependencies=[Depends(exigir_acceso)])
    def animacion(id_: str):
        """Binario: uint32 n_piezas, uint32 n_cuadros, float32 fps, uint32[n] cuadro de aparición,
        float32[n_cuadros][n_piezas][7] = x, y, z (mm, marco del embalaje), qx, qy, qz, qw."""
        t = app.state.almacen.obtener(id_)
        if not t or t.estado != "listo" or not t.animacion:
            raise HTTPException(404, "La animación no está disponible.")
        return Response(t.animacion, media_type="application/octet-stream")

    @app.delete("/v1/trabajos/{id_}", dependencies=[Depends(exigir_acceso)])
    @app.delete("/v1/simulaciones/{id_}", dependencies=[Depends(exigir_acceso)], include_in_schema=False)
    def borrar(id_: str):
        if not app.state.almacen.borrar(id_):
            raise HTTPException(404, "La simulación no existe o ya venció.")
        return {"borrada": True}

    # ───────────── interfaz web (etapa 3) ─────────────
    if os.path.isdir(WEB):
        app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
    else:
        @app.get("/")
        def inicio():
            return {"servicio": "Packsim", "version": __version__, "interfaz": "llega en la etapa 3"}

    return app


async def _leer_limitado(archivo: UploadFile, mb: int) -> bytes:
    maximo, partes, total = mb * 1024 * 1024, [], 0
    while True:
        bloque = await archivo.read(1024 * 1024)
        if not bloque:
            break
        total += len(bloque)
        if total > maximo:
            raise HTTPException(413, f"El archivo supera el máximo de {mb} MB.")
        partes.append(bloque)
    await archivo.close()
    return b"".join(partes)


def _memoria_contenedor_mb():
    for ruta in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            v = open(ruta).read().strip()
            return None if v == "max" or int(v) > 1 << 50 else round(int(v) / 1024 / 1024)
        except (OSError, ValueError):
            pass
    return None


def _msg(e: dict) -> str:
    campo = ".".join(str(x) for x in e.get("loc", []) if x not in ("body",))
    return f"{campo}: {e.get('msg', '')}".strip(": ")


app = crear_app()
