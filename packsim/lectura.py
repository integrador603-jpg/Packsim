"""
Lectura de archivos 3D sin persistencia.

Los bytes se procesan en memoria. Cuando un conversor necesita archivos (DWG), se usa una carpeta
temporal que se borra siempre al terminar, aunque haya errores. Nada se escribe fuera de esa carpeta.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile

import numpy as np
import trimesh

from .catalogo import DENSIDADES
from .modelos import Pieza, volumen_seguro

FORMATOS = ("stl", "obj", "ply", "glb", "step", "stp", "iges", "igs", "dxf", "dwg")
TAMANO_MAX = 50 * 1024 * 1024
UNIDADES = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}


class ErrorLectura(ValueError):
    pass


def leer_pieza(datos: bytes, nombre_archivo: str, unidades: str = "mm", material: str = "acero",
               masa_kg: float | None = None, nombre: str | None = None) -> Pieza:
    """Lee una pieza desde los bytes de un archivo. Devuelve la malla en mm."""
    if len(datos) > TAMANO_MAX:
        raise ErrorLectura(f"El archivo supera el máximo de {TAMANO_MAX // (1024 * 1024)} MB.")
    ext = nombre_archivo.rsplit(".", 1)[-1].lower() if "." in nombre_archivo else ""
    if ext not in FORMATOS:
        raise ErrorLectura(f"Formato no soportado (.{ext}). Usá STEP, IGES, STL, OBJ, GLB, DXF o DWG.")
    if unidades not in UNIDADES:
        raise ErrorLectura(f"Unidades no válidas: {unidades}")

    unidades_del_archivo = False
    if ext in ("step", "stp", "iges", "igs"):
        malla = _leer_cad(datos, ext)
        unidades_del_archivo = True                 # OpenCascade convierte a mm según el archivo
    elif ext == "dxf":
        malla = _desde_dxf(datos)
    elif ext == "dwg":
        malla = _leer_dwg(datos)
    else:
        malla = trimesh.load(io.BytesIO(datos), file_type=ext, force="mesh")
        if not isinstance(malla, trimesh.Trimesh) or len(malla.faces) == 0:
            raise ErrorLectura("El archivo no contiene superficies 3D.")

    malla = limpiar(malla)
    if not unidades_del_archivo:
        malla.apply_scale(UNIDADES[unidades])
    if len(malla.faces) == 0:
        raise ErrorLectura("El archivo no contiene superficies 3D.")
    if float(malla.extents.max()) <= 0:
        raise ErrorLectura("La pieza tiene medidas nulas.")

    vol = volumen_seguro(malla)
    if masa_kg and masa_kg > 0:
        masa, origen = float(masa_kg), "cargada"
    else:
        masa, origen = vol * DENSIDADES.get(material, 7.85) / 1e6, "material × volumen"
    return Pieza(nombre=nombre or nombre_archivo.rsplit(".", 1)[0], malla=malla, masa_kg=masa,
                 origen_masa=origen, descripcion=f"{len(malla.faces):,} triángulos".replace(",", "."),
                 norma=nombre_archivo, material=material, volumen_mm3=vol)


def limpiar(m: trimesh.Trimesh) -> trimesh.Trimesh:
    m = m.copy()
    m.merge_vertices(digits_vertex=3)
    m.update_faces(m.nondegenerate_faces())
    m.update_faces(m.unique_faces())
    m.remove_unreferenced_vertices()
    if m.is_watertight and m.volume < 0:
        m.invert()
    return m


def advertencias(p: Pieza) -> list[str]:
    """Avisos sobre la calidad de la pieza leída."""
    out = []
    ext = p.envolvente_mm
    if not p.malla.is_watertight:
        out.append("La malla no es un sólido cerrado: el volumen se calculó con la envolvente convexa y puede estar sobreestimado.")
    if ext.max() < 2:
        out.append(f"La pieza mide menos de 2 mm: verificá que las unidades no sean metros o pulgadas.")
    if ext.max() > 5000:
        out.append(f"La pieza mide más de 5 m: verificá que las unidades no sean micrones o décimas.")
    return out


# ─────────────── STEP / IGES con OpenCascade ───────────────

def _leer_cad(datos: bytes, ext: str) -> trimesh.Trimesh:
    try:
        from OCP.BRep import BRep_Tool
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.Interface import Interface_Static
        from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopLoc import TopLoc_Location
        from OCP.TopoDS import TopoDS
        from OCP.Bnd import Bnd_Box
        from OCP.BRepBndLib import BRepBndLib
    except ImportError as e:  # pragma: no cover
        raise ErrorLectura("El lector STEP/IGES no está instalado en el servidor.") from e

    tmp = tempfile.mkdtemp(prefix="packsim_")
    try:
        ruta = os.path.join(tmp, "pieza." + ext)
        with open(ruta, "wb") as fh:
            fh.write(datos)
        if ext in ("step", "stp"):
            from OCP.STEPControl import STEPControl_Reader
            lector = STEPControl_Reader()
        else:
            from OCP.IGESControl import IGESControl_Reader
            lector = IGESControl_Reader()
        Interface_Static.SetCVal_s("xstep.cascade.unit", "MM")
        if lector.ReadFile(ruta) != IFSelect_RetDone:
            raise ErrorLectura(f"No se pudo leer el archivo {ext.upper()}.")
        lector.TransferRoots()
        forma = lector.OneShape()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    caja = Bnd_Box()
    BRepBndLib.Add_s(forma, caja)
    a, b = caja.CornerMin(), caja.CornerMax()
    diag = float(np.linalg.norm([b.X() - a.X(), b.Y() - a.Y(), b.Z() - a.Z()]))
    BRepMesh_IncrementalMesh(forma, max(diag * 0.001, 0.01), False, 0.35, True)

    verts, caras, base = [], [], 0
    exp = TopExp_Explorer(forma, TopAbs_FACE)
    while exp.More():
        cara = (getattr(TopoDS, 'Face_s', None) or TopoDS.Face)(exp.Current())
        loc = TopLoc_Location()
        tri = (getattr(BRep_Tool, 'Triangulation_s', None) or BRep_Tool.Triangulation)(cara, loc)
        if tri is not None:
            trsf = loc.Transformation()
            n = tri.NbNodes()
            for i in range(1, n + 1):
                p = tri.Node(i).Transformed(trsf)
                verts.append((p.X(), p.Y(), p.Z()))
            invertida = cara.Orientation() == TopAbs_REVERSED
            for i in range(1, tri.NbTriangles() + 1):
                a, b, c = tri.Triangle(i).Get()
                caras.append((base + a - 1, base + c - 1, base + b - 1) if invertida else (base + a - 1, base + b - 1, base + c - 1))
            base += n
        exp.Next()
    if not caras:
        raise ErrorLectura("El archivo no contiene sólidos o superficies triangulables.")
    return trimesh.Trimesh(np.array(verts), np.array(caras), process=False)


# ─────────────── DXF (3DFACE) y DWG ───────────────

def _desde_dxf(datos: bytes) -> trimesh.Trimesh:
    from ezdxf import recover
    caras = []
    try:
        doc, _ = recover.read(io.BytesIO(datos))      # tolera DXF de otros programas
        caras = [[np.array(e.dxf.get(f"vtx{i}"), dtype=float) for i in range(4)] for e in doc.modelspace().query("3DFACE")]
    except Exception:
        caras = _caras_dxf_crudo(datos)               # último recurso: leer los códigos de grupo directamente
        if caras is None:
            raise ErrorLectura("El DXF está dañado o no se puede leer.")
    tris = []
    for v in caras:
        tris.append(v[:3])
        if np.linalg.norm(v[3] - v[2]) > 1e-9:
            tris.append([v[0], v[2], v[3]])
    if not tris:
        raise ErrorLectura("El dibujo no trae caras 3D. Si es un plano 2D (vistas y cotas) no hay sólido para simular: "
                           "exportá la pieza en 3D como STEP o STL.")
    t = np.asarray(tris)
    return trimesh.Trimesh(t.reshape(-1, 3), np.arange(len(t) * 3).reshape(-1, 3), process=False)


def _caras_dxf_crudo(datos: bytes):
    """Extrae entidades 3DFACE de un DXF ASCII leyendo pares (código, valor)."""
    try:
        lineas = [l.strip() for l in datos.decode("utf-8", errors="replace").splitlines()]
    except Exception:
        return None
    caras, i = [], 0
    while i + 1 < len(lineas):
        if lineas[i] == "0" and lineas[i + 1] == "3DFACE":
            val, j = {}, i + 2
            while j + 1 < len(lineas) and lineas[j] != "0":
                try:
                    val[int(lineas[j])] = float(lineas[j + 1])
                except ValueError:
                    pass
                j += 2
            caras.append([np.array([val.get(10 + k, 0.0), val.get(20 + k, 0.0), val.get(30 + k, 0.0)]) for k in range(4)])
            i = j
        else:
            i += 2
    return caras


def _leer_dwg(datos: bytes, tiempo_max_s: int = 60) -> trimesh.Trimesh:
    exe = os.environ.get("PACKSIM_DWG2DXF") or shutil.which("dwg2dxf")
    if not exe:
        raise ErrorLectura("El conversor de DWG no está instalado en el servidor.")
    tmp = tempfile.mkdtemp(prefix="packsim_")
    try:
        entrada, salida = os.path.join(tmp, "pieza.dwg"), os.path.join(tmp, "pieza.dxf")
        with open(entrada, "wb") as fh:
            fh.write(datos)
        try:
            r = subprocess.run([exe, "-y", "-o", salida, entrada], capture_output=True, timeout=tiempo_max_s,
                               cwd=tmp, env={"PATH": os.environ.get("PATH", ""), "LD_LIBRARY_PATH": os.environ.get("LD_LIBRARY_PATH", "")})
        except subprocess.TimeoutExpired:
            raise ErrorLectura("La conversión del DWG tardó demasiado y se canceló.")
        if not os.path.exists(salida):
            raise ErrorLectura("No se pudo convertir el DWG. Exportalo como STEP o STL desde el CAD.")
        with open(salida, "rb") as fh:
            dxf = fh.read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return _desde_dxf(dxf)
