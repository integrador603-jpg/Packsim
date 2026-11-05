"""
Simulación física con PyBullet (corre en el proceso aislado de la API).

Decisiones:
- Escala: el mundo se mide en "tamaños de pieza" (la dimensión mayor de la pieza = 1 unidad) y la
  gravedad se escala igual, así la dinámica en el tiempo es la real y Bullet trabaja en su rango óptimo
  aunque la pieza mida 3 mm o 600 mm.
- Forma: la pieza se descompone en partes convexas (V-HACD), así conserva agujeros y entrantes.
- Vibración: se aplica como aceleración inercial (gravedad variable) sobre una caja fija; es
  equivalente a mover la caja y mucho más estable numéricamente.
- Colisión continua (CCD) para que las piezas finas no atraviesen paredes.
- Piezas chicas en cantidad: se simula una muestra del embalaje y se extrapola (se informa).
"""
from __future__ import annotations

import math
import os
import shutil
import struct
import tempfile
import time

import numpy as np

from .modelos import Embalaje, Pieza

G_MM = 9810.0                 # mm/s²
PASO = 1 / 120
FPS_ANIM = 12
CUERPOS_MAX = 420             # tope por simulación (rendimiento)
OBJETIVO_MUESTRA = 140        # piezas aproximadas en la muestra cuando el embalaje es grande


class ErrorFisica(ValueError):
    pass


def _pb():
    try:
        import pybullet as pb
        return pb
    except ImportError as e:  # pragma: no cover
        raise ErrorFisica("El motor de física no está instalado en el servidor.") from e


def _quat_de_matriz(R):
    R = np.asarray(R, dtype=float)
    t = np.trace(R)
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        return ((R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s, 0.25 * s)
    i = int(np.argmax(np.diag(R)))
    j, k = (i + 1) % 3, (i + 2) % 3
    s = math.sqrt(1.0 + R[i, i] - R[j, j] - R[k, k]) * 2
    q = [0.0, 0.0, 0.0, (R[k, j] - R[j, k]) / s]
    q[i] = 0.25 * s
    q[j] = (R[j, i] + R[i, j]) / s
    q[k] = (R[k, i] + R[i, k]) / s
    return tuple(q)


class Mundo:
    """Una caja (fondo + 4 paredes altas) y piezas iguales con forma convexa descompuesta."""

    def __init__(self, pieza: Pieza, interior_mm, friccion_caja: float, semilla: int = 1, tapa: bool = False,
                 preciso: bool = False):
        self.pb = pb = _pb()
        self.pieza = pieza
        self.L, self.W, self.H = [float(x) for x in interior_mm]
        self.dmax = float(pieza.envolvente_mm.max())
        self.s = 1.0 / self.dmax                              # unidades por mm
        self.rng = np.random.default_rng(semilla)
        self.cid = pb.connect(pb.DIRECT)
        # contactERP alto: corrige rápido las penetraciones bajo el peso de la pila (con el valor por defecto,
        # las piezas de abajo quedaban hundidas hasta 10 mm en el fondo e inflaban el conteo)
        # preciso=True (validación de un acomodo trabado contra la tapa): más iteraciones y 2 subpasos; con la
        # configuración rápida un bloque compacto acumulaba energía y "explotaba".
        it, sub, erp = (50, 2, 0.4) if preciso else (25, 1, 0.8)
        pb.setPhysicsEngineParameter(fixedTimeStep=PASO, numSolverIterations=it, numSubSteps=sub,
                                     erp=erp, contactERP=erp, frictionERP=0.2,
                                     enableConeFriction=1, deterministicOverlappingPairs=1,
                                     physicsClientId=self.cid)
        self.g = G_MM * self.s
        pb.setGravity(0, 0, -self.g, physicsClientId=self.cid)
        self._tmp = tempfile.mkdtemp(prefix="packsim_")
        try:
            self.forma = self._forma_pieza()
        except Exception:
            self.cerrar()
            raise
        self._caja(friccion_caja, tapa)
        self.cuerpos: list[int] = []
        self.nacido: list[int] = []
        self.t = 0.0
        self.cuadros: list[list] = []
        self._prox_cuadro = 0.0

    # ───── geometría ─────
    def _forma_pieza(self):
        pb, m = self.pb, self.pieza.malla.copy()
        m.apply_translation(-self.pieza.centro_mm)
        m.apply_scale(self.s)
        if len(m.faces) > 20_000:
            try:
                m = m.simplify_quadric_decimation(face_count=20_000)
            except Exception:
                pass
        entrada, salida = os.path.join(self._tmp, "pieza.obj"), os.path.join(self._tmp, "partes.obj")
        m.export(entrada)
        if m.is_watertight and m.is_convex:
            h = m.convex_hull
            if len(h.vertices) > 64:                          # casco convexo liviano: mucho más rápido de simular
                try:
                    h = h.simplify_quadric_decimation(face_count=120).convex_hull
                except Exception:
                    pass
            h.export(salida)
        else:
            fd = os.dup(1)                                    # V-HACD escribe progreso en la salida estándar: se silencia
            nulo = os.open(os.devnull, os.O_WRONLY)
            try:
                os.dup2(nulo, 1)
                pb.vhacd(entrada, salida, os.path.join(self._tmp, "vhacd.log"), resolution=200_000, concavity=0.001,
                         maxNumVerticesPerCH=24, minVolumePerCH=0.00005, physicsClientId=self.cid)
            finally:
                os.dup2(fd, 1); os.close(fd); os.close(nulo)
            if not os.path.exists(salida) or os.path.getsize(salida) == 0:
                shutil.copy(entrada, salida)
        forma = pb.createCollisionShape(pb.GEOM_MESH, fileName=salida, physicsClientId=self.cid)
        if forma < 0:
            raise ErrorFisica("No se pudo crear la forma física de la pieza.")
        return forma

    def _caja(self, fric, tapa=False):
        pb, s = self.pb, self.s
        L, W, H = self.L * s, self.W * s, self.H * s
        t = 1.0                                               # espesor de pared = 1 tamaño de pieza
        alto = H + 4.0
        partes = [((L / 2 + t, W / 2 + t, t / 2), (0, 0, -t / 2)),
                  ((t / 2, W / 2 + t, alto / 2), (L / 2 + t / 2, 0, alto / 2)),
                  ((t / 2, W / 2 + t, alto / 2), (-L / 2 - t / 2, 0, alto / 2)),
                  ((L / 2, t / 2, alto / 2), (0, W / 2 + t / 2, alto / 2)),
                  ((L / 2, t / 2, alto / 2), (0, -W / 2 - t / 2, alto / 2))]
        if tapa:                                              # embalaje cerrado (transporte)
            partes.append(((L / 2 + t, W / 2 + t, t / 2), (0, 0, H + t / 2)))
        formas = [pb.createCollisionShape(pb.GEOM_BOX, halfExtents=he, physicsClientId=self.cid) for he, _ in partes]
        for f, (_, pos) in zip(formas, partes):
            b = pb.createMultiBody(0, f, -1, pos, physicsClientId=self.cid)
            pb.changeDynamics(b, -1, lateralFriction=fric, restitution=0.05, collisionMargin=0.001, physicsClientId=self.cid)
        self.Ls, self.Ws, self.Hs = L, W, H

    def agregar(self, pos_u, quat):
        pb = self.pb
        b = pb.createMultiBody(max(self.pieza.masa_kg, 1e-5), self.forma, -1, pos_u, quat, physicsClientId=self.cid)
        dmin = float(self.pieza.envolvente_mm.min()) * self.s
        pb.changeDynamics(b, -1, lateralFriction=0.4, restitution=0.05, rollingFriction=0.0005, spinningFriction=0.0005,
                          linearDamping=0.04, angularDamping=0.08, ccdSweptSphereRadius=max(0.05, 0.35 * dmin),
                          # margen de colisión mínimo: el de Bullet por defecto (0,04) es más que la holgura entre piezas
                          collisionMargin=0.002 * min(1.0, dmin), physicsClientId=self.cid)
        self.cuerpos.append(b)
        self.nacido.append(len(self.cuadros))
        return b

    # ───── tiempo ─────
    def avanzar(self, segundos: float, aceleracion=None):
        """aceleracion(t) → (ax, ay, az) de la caja en mm/s²; se aplica como inercia."""
        pb, n = self.pb, max(1, int(round(segundos / PASO)))
        for _ in range(n):
            if aceleracion:
                ax, ay, az = aceleracion(self.t)
                pb.setGravity(-ax * self.s, -ay * self.s, -self.g - az * self.s, physicsClientId=self.cid)
            pb.stepSimulation(physicsClientId=self.cid)
            self.t += PASO
            if self.t >= self._prox_cuadro:
                self._grabar()
                self._prox_cuadro += 1 / FPS_ANIM
        if aceleracion:
            pb.setGravity(0, 0, -self.g, physicsClientId=self.cid)

    def asentar(self, max_s: float = 2.0, umbral: float = 0.08):
        """Avanza hasta que todas las piezas están casi quietas (o se acaba el tiempo)."""
        t0 = self.t
        while self.t - t0 < max_s:
            self.avanzar(0.1)
            if self._velocidad_max() < umbral:
                return True
        return False

    def _velocidad_max(self):
        pb = self.pb
        v = 0.0
        for b in self.cuerpos:
            lin, _ = pb.getBaseVelocity(b, physicsClientId=self.cid)
            v = max(v, math.sqrt(lin[0] ** 2 + lin[1] ** 2 + lin[2] ** 2))
        return v

    def _grabar(self):
        pb, s = self.pb, self.s
        fila = []
        for b in self.cuerpos:
            p, q = pb.getBasePositionAndOrientation(b, physicsClientId=self.cid)
            fila.append((p[0] / s + self.L / 2, p[1] / s + self.W / 2, p[2] / s, q[0], q[1], q[2], q[3]))
        self.cuadros.append(fila)

    # ───── mediciones ─────
    def tope_mm(self, b):
        lo, hi = self.pb.getAABB(b, physicsClientId=self.cid)
        return hi[2] / self.s

    def dentro(self, tol_mm=None):
        tol = (0.02 * self.dmax) if tol_mm is None else tol_mm
        return [b for b in self.cuerpos if self.tope_mm(b) <= self.H + tol]

    def penetracion_max_mm(self) -> float:
        """Cuánto se mete la malla real de alguna pieza en el fondo o las paredes (indicador de calidad)."""
        V = self.pieza.malla.vertices - self.pieza.centro_mm
        peor = 0.0
        for b in self.cuerpos:
            c, R = self.pose_mm(b)
            P = V @ R.T + c
            peor = max(peor, -P[:, 2].min(), -P[:, 0].min(), P[:, 0].max() - self.L, -P[:, 1].min(), P[:, 1].max() - self.W)
        return round(float(peor), 2)

    def pose_mm(self, b):
        pb = self.pb
        p, q = pb.getBasePositionAndOrientation(b, physicsClientId=self.cid)
        R = np.array(pb.getMatrixFromQuaternion(q)).reshape(3, 3)
        return np.array([p[0] / self.s + self.L / 2, p[1] / self.s + self.W / 2, p[2] / self.s]), R

    def animacion(self) -> bytes:
        """Binario compacto: cabecera (n_cuerpos, n_cuadros, fps) + nacimiento de cada cuerpo + float32 [x,y,z,qx,qy,qz,qw]."""
        cuadros = self.cuadros
        if len(cuadros) > 480:                               # tope de tamaño: se submuestrea
            paso = math.ceil(len(cuadros) / 480)
            idx = list(range(0, len(cuadros), paso))
            if idx[-1] != len(cuadros) - 1:
                idx.append(len(cuadros) - 1)
            nacido = [next(i for i, c in enumerate(idx) if c >= n) if n <= idx[-1] else len(idx) - 1 for n in self.nacido]
            cuadros = [cuadros[i] for i in idx]
            fps = FPS_ANIM / paso
        else:
            nacido, fps = self.nacido, float(FPS_ANIM)
        n, f = len(self.cuerpos), len(cuadros)
        datos = np.full((f, n, 7), np.nan, dtype=np.float32)
        for i, fila in enumerate(cuadros):
            if fila:
                datos[i, :len(fila)] = np.asarray(fila, dtype=np.float32)
        return struct.pack("<IIf", n, f, fps) + np.asarray(nacido, dtype=np.uint32).tobytes() + datos.tobytes()

    def cerrar(self):
        try:
            self.pb.disconnect(physicsClientId=self.cid)
        except Exception:
            pass
        shutil.rmtree(self._tmp, ignore_errors=True)


# ─────────────── perfiles de vibración ───────────────

def perfil_asentamiento(g=G_MM):
    """Vibrado para acomodar a granel: ~0,5 g horizontal rotando y 0,35 g vertical a 7–9 Hz."""
    def a(t):
        w = 2 * math.pi * 8
        return (0.5 * g * math.sin(w * t), 0.5 * g * math.cos(w * t * 0.93), 0.35 * g * math.sin(w * t * 1.07 + 1.0))
    return a


def perfil_transporte(semilla=7, g=G_MM):
    """Ensayo acelerado inspirado en vibración de camión (3–25 Hz, ≈0,5 g RMS vertical, 0,25 g horizontal)."""
    rng = np.random.default_rng(semilla)
    fr = rng.uniform(3, 25, 8)
    fa = rng.uniform(0, 2 * math.pi, (3, 8))
    escalas = (0.25 * g * math.sqrt(2 / 8), 0.25 * g * math.sqrt(2 / 8), 0.5 * g * math.sqrt(2 / 8))

    def a(t):
        return tuple(e * sum(math.sin(2 * math.pi * f * t + ph) for f, ph in zip(fr, fa[k])) for k, e in enumerate(escalas))
    return a


# ─────────────── volcado a granel ───────────────

def granel(pieza: Pieza, emb: Embalaje, friccion_caja: float = 0.45, avisar=None, semilla: int = 1,
           tiempo_max_s: float = 90) -> dict:
    avisar = avisar or (lambda f, txt: None)
    L, W, H = [float(x) for x in emb.interior_mm]
    ext = pieza.envolvente_mm
    if any(sorted(ext)[i] > sorted([L, W, H])[i] for i in range(3)):
        raise ErrorFisica("La pieza no entra en el embalaje.")
    try:
        v_conv = float(pieza.malla.convex_hull.volume)
    except Exception:
        v_conv = float(np.prod(ext))
    estimado = 0.62 * L * W * H / max(v_conv, 1e-9)
    dims, extrapolado = (L, W, H), False
    if estimado > OBJETIVO_MUESTRA * 1.6:
        f = (OBJETIVO_MUESTRA / estimado) ** (1 / 3)
        minimo = 5 * float(ext.max())
        dims = tuple(min(d, max(minimo, d * f)) for d in (L, W, H))
        extrapolado = True

    mundo = Mundo(pieza, dims, friccion_caja, semilla)
    t_ini = time.monotonic()
    try:
        Ls, Ws, Hs = mundo.Ls, mundo.Ws, mundo.Hs
        r = 0.5 * float(np.linalg.norm(ext)) * mundo.s      # radio de la esfera envolvente (unidades)
        paso = 2 * r * 1.05
        nx, ny = max(1, int((Ls - 2 * r) // paso) + 1), max(1, int((Ws - 2 * r) // paso) + 1)
        anterior, ciclos = -1, 0
        while ciclos < 5:
            ciclos += 1
            # 1) llenar hasta rebalsar
            while len(mundo.cuerpos) < CUERPOS_MAX and time.monotonic() - t_ini < tiempo_max_s * 0.8:
                topes = [mundo.tope_mm(b) * mundo.s for b in mundo.cuerpos]
                cima = max(topes) if topes else 0.0
                if cima > Hs + 0.6:
                    break
                z = max(cima, 0.0) + r + 0.05
                lugares = [(-Ls / 2 + r + i * paso + mundo.rng.uniform(-0.05, 0.05) * paso,
                            -Ws / 2 + r + j * paso + mundo.rng.uniform(-0.05, 0.05) * paso) for i in range(nx) for j in range(ny)]
                mundo.rng.shuffle(lugares)
                for x, y in lugares[:CUERPOS_MAX - len(mundo.cuerpos)]:
                    q = mundo.rng.normal(size=4); q /= np.linalg.norm(q)
                    mundo.agregar((min(max(x, -Ls / 2 + r), Ls / 2 - r), min(max(y, -Ws / 2 + r), Ws / 2 - r), z), tuple(q))
                mundo.asentar(0.8, umbral=0.25)
                avisar(min(0.85, 0.1 + 0.7 * len(mundo.dentro()) / max(estimado if not extrapolado else OBJETIVO_MUESTRA, 1)),
                       f"Volcando piezas… {len(mundo.cuerpos)} en la caja")
            # 2) vibrar y asentar
            avisar(0.86, "Vibrando el embalaje…")
            mundo.avanzar(2.0, perfil_asentamiento())
            mundo.asentar(1.5)
            adentro = len(mundo.dentro())
            # se corta cuando un nuevo ciclo casi no suma piezas (< 2%)
            if adentro <= anterior * 1.02 or len(mundo.cuerpos) >= CUERPOS_MAX or time.monotonic() - t_ini > tiempo_max_s * 0.8:
                break
            anterior = adentro
        dentro = mundo.dentro()
        n = len(dentro)
        colocaciones = []
        for b in dentro:
            c, R = mundo.pose_mm(b)
            colocaciones.append({"centro_mm": [round(float(v), 3) for v in c], "rotacion": np.round(R, 5).tolist()})
        colocaciones.sort(key=lambda d: d["centro_mm"][2])
        vol_muestra = dims[0] * dims[1] * dims[2]
        total = _extrapolar(colocaciones, dims, (L, W, H), float(ext.max())) if extrapolado else n
        avisar(0.97, "Preparando el resultado…")
        return {
            "piezas_que_entran": total,
            "extrapolado": extrapolado,
            "muestra": {"interior_mm": [round(d, 1) for d in dims], "piezas": n, "volcadas": len(mundo.cuerpos)} if extrapolado else None,
            "ciclos": ciclos,
            "rebalso": len(mundo.cuerpos) > n,
            "tope_de_cuerpos": len(mundo.cuerpos) >= CUERPOS_MAX,
            "fraccion_volumen": round(n * pieza.volumen_mm3 / vol_muestra, 4),
            "tiempo_simulado_s": round(mundo.t, 2),
            "penetracion_max_mm": mundo.penetracion_max_mm(),
            "disposicion": colocaciones,
            "interior_simulado_mm": [round(d, 1) for d in dims],
            "animacion": mundo.animacion(),
        }
    finally:
        mundo.cerrar()


def _extrapolar(colocaciones, dims, destino, dmax) -> int:
    """
    Lleva el conteo de la muestra al embalaje completo con un modelo de bordes:
        N(caja) = ρ · V − k · S
    ρ = piezas por mm³ en el interior de la muestra (lejos de paredes y de la superficie),
    S = superficie de la caja (fondo, paredes y tapa) y k = déficit de piezas por mm² de borde,
    calibrado con la misma muestra. Una regla de tres subestimaría: en una caja chica los bordes pesan más.
    """
    L, W, H = dims
    m = dmax
    lo, hi = np.array([m, m, m]), np.array([L - m, W - m, H - 1.5 * m])
    if np.any(hi - lo <= 0):
        n = len(colocaciones)
        return int(n * np.prod(destino) / (L * W * H))
    C = np.array([c["centro_mm"] for c in colocaciones])
    adentro = np.all((C >= lo) & (C <= hi), axis=1).sum()
    rho = adentro / float(np.prod(hi - lo))
    def area(a, b, c):
        return 2 * (a * b + a * c + b * c)
    k = max(0.0, (rho * L * W * H - len(colocaciones)) / area(L, W, H))
    Ld, Wd, Hd = destino
    return max(len(colocaciones), int(rho * Ld * Wd * Hd - k * area(Ld, Wd, Hd)))


# ─────────────── validación de un acomodo ───────────────

def validar(pieza: Pieza, emb: Embalaje, colocaciones: list, friccion_caja: float = 0.45, avisar=None,
            duracion_s: float = 4.0, semilla: int = 7) -> dict:
    """Somete el acomodo a vibración de transporte y mide cuánto se mueve cada pieza."""
    avisar = avisar or (lambda f, txt: None)
    if not colocaciones:
        raise ErrorFisica("No hay piezas para validar.")
    if len(colocaciones) > CUERPOS_MAX:
        raise ErrorFisica(f"Son {len(colocaciones)} piezas: la validación física admite hasta {CUERPOS_MAX} por ahora.")
    mundo = Mundo(pieza, emb.interior_mm, friccion_caja, semilla, tapa=True, preciso=True)
    try:
        s, c0 = mundo.s, pieza.centro_mm
        for col in colocaciones:
            R = np.asarray(col.rotacion if hasattr(col, "rotacion") else col["rotacion"], dtype=float)
            cen = np.asarray(col.centro_mm if hasattr(col, "centro_mm") else col["centro_mm"], dtype=float)
            # la forma física está centrada en el centro de la envolvente: posición = centro del acomodo
            mundo.agregar(((cen[0] - mundo.L / 2) * s, (cen[1] - mundo.W / 2) * s, cen[2] * s + 0.002), _quat_de_matriz(R))
        avisar(0.15, "Asentando el acomodo…")
        mundo.asentar(1.0)
        base = [mundo.pose_mm(b) for b in mundo.cuerpos]
        avisar(0.35, "Simulando vibración de transporte…")
        mundo.avanzar(duracion_s, perfil_transporte())
        avisar(0.85, "Midiendo desplazamientos…")
        mundo.asentar(1.0)
        desp, giro = [], []
        eje = pieza.redonda.eje if pieza.redonda else None
        for b, (p0, R0) in zip(mundo.cuerpos, base):
            p1, R1 = mundo.pose_mm(b)
            desp.append(float(np.linalg.norm(p1 - p0)))
            if eje is not None:   # pieza redonda: girar sobre su eje no cambia nada; se mide cuánto se inclina el eje
                cosang = float(np.dot(R0[:, eje], R1[:, eje]))
            else:
                cosang = (np.trace(R0.T @ R1) - 1) / 2
            giro.append(math.degrees(math.acos(max(-1.0, min(1.0, cosang)))))
        # con la tapa puesta una pieza apretada contra ella puede asomar algún mm por la tolerancia del
        # contacto: se cuenta como "fuera" sólo la que tiene el centro fuera del interior
        lim = np.array([mundo.L, mundo.W, mundo.H])
        fuera = sum(1 for b in mundo.cuerpos if np.any(mundo.pose_mm(b)[0] < 0) or np.any(mundo.pose_mm(b)[0] > lim))
        dmax = float(pieza.envolvente_mm.max())
        volcadas = sum(1 for g in giro if g > 30)
        corridas = sum(1 for d, g in zip(desp, giro) if g <= 30 and d > 0.15 * dmax)
        if fuera or volcadas > 0.05 * len(desp):
            estado = "se_desarma"
        elif volcadas or corridas > 0.1 * len(desp):
            estado = "se_reacomoda"
        else:
            estado = "se_mantiene"
        return {
            "estado": estado,
            "estable": estado == "se_mantiene",
            "piezas": len(desp),
            "piezas_fuera": fuera,
            "piezas_volcadas": volcadas,
            "piezas_corridas": corridas,
            "desplazamiento_max_mm": round(max(desp), 2),
            "desplazamiento_medio_mm": round(float(np.mean(desp)), 2),
            "giro_max_grados": round(max(giro), 1),
            "criterio": "volcada: gira más de 30°; corrida: se desplaza más del 15% de su largo",
            "perfil": "transporte en camión con el embalaje cerrado (ensayo acelerado, 3–25 Hz, ≈0,5 g RMS vertical)",
            "duracion_simulada_s": duracion_s,
            "penetracion_max_mm": mundo.penetracion_max_mm(),
            "animacion": mundo.animacion(),
        }
    finally:
        mundo.cerrar()
