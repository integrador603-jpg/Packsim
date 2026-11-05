import glob
import io
import os
import shutil
import subprocess
import tempfile

import ezdxf
import numpy as np
import pytest
import trimesh

from packsim.catalogo import construir
from packsim.lectura import ErrorLectura, advertencias, leer_pieza


def _temporales():
    return set(glob.glob(os.path.join(tempfile.gettempdir(), "packsim_*")))


def _dxf_de(malla) -> bytes:
    doc = ezdxf.new()
    msp = doc.modelspace()
    for tri in malla.triangles:
        a, b, c = [tuple(map(float, v)) for v in tri]
        msp.add_3dface([a, b, c, c])
    s = io.StringIO()
    doc.write(s)
    return s.getvalue().encode()


def test_stl_en_memoria_y_unidades():
    ref = construir("buje", {"diametro": 20, "interior": 10, "largo": 25})
    datos = ref.malla.export(file_type="stl")
    p = leer_pieza(datos, "buje.stl", masa_kg=0.05)
    assert p.volumen_mm3 == pytest.approx(ref.volumen_mm3, rel=1e-3)
    assert p.masa_kg == 0.05 and p.origen_masa == "cargada"
    p_cm = leer_pieza(datos, "buje.stl", unidades="cm")
    assert p_cm.envolvente_mm.max() == pytest.approx(250, rel=1e-3)


def test_dxf_con_caras_3d():
    caja = trimesh.creation.box((40, 30, 20))
    p = leer_pieza(_dxf_de(caja), "caja.dxf")
    assert p.volumen_mm3 == pytest.approx(24000, rel=1e-3)
    assert advertencias(p) == []


def test_dxf_plano_2d_da_error_claro():
    doc = ezdxf.new()
    doc.modelspace().add_line((0, 0), (100, 0))
    s = io.StringIO(); doc.write(s)
    with pytest.raises(ErrorLectura, match="plano 2D"):
        leer_pieza(s.getvalue().encode(), "plano.dxf")


def test_formato_no_soportado():
    with pytest.raises(ErrorLectura, match="no soportado"):
        leer_pieza(b"hola", "pieza.pdf")


def test_step_respeta_unidades_del_archivo():
    pytest.importorskip("OCP")
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.Interface import Interface_Static
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

    antes = _temporales()
    d = tempfile.mkdtemp()
    try:
        ruta = os.path.join(d, "cubo.step")
        w = STEPControl_Writer()                       # crea las opciones del traductor STEP
        assert Interface_Static.SetCVal_s("write.step.unit", "INCH")
        w.Transfer(BRepPrimAPI_MakeBox(50.8, 25.4, 25.4).Shape(), STEPControl_AsIs)   # se escribe como 2 × 1 × 1 pulgadas
        w.Write(ruta)
        Interface_Static.SetCVal_s("write.step.unit", "MM")
        datos = open(ruta, "rb").read()
        assert b"INCH" in datos.upper()
    finally:
        shutil.rmtree(d)
    p = leer_pieza(datos, "cubo.step")
    assert sorted(p.envolvente_mm.round(1)) == pytest.approx(sorted([50.8, 25.4, 25.4]), abs=0.1)
    assert p.malla.is_watertight
    assert p.volumen_mm3 == pytest.approx(50.8 * 25.4 * 25.4, rel=1e-3)
    assert _temporales() == antes        # no quedan archivos temporales


def test_dwg_se_convierte_y_no_deja_archivos():
    exe = os.environ.get("PACKSIM_DWG2DXF") or shutil.which("dwg2dxf")
    dxf2dwg = shutil.which("dxf2dwg") or (exe and os.path.join(os.path.dirname(exe), "dxf2dwg"))
    if not exe or not dxf2dwg or not os.path.exists(dxf2dwg):
        pytest.skip("LibreDWG no está instalado")
    d = tempfile.mkdtemp()
    try:
        caja = trimesh.creation.box((40, 30, 20))
        open(os.path.join(d, "c.dxf"), "wb").write(_dxf_de(caja))
        subprocess.run([dxf2dwg, "-y", "-o", os.path.join(d, "c.dwg"), os.path.join(d, "c.dxf")], capture_output=True, timeout=60)
        if not os.path.exists(os.path.join(d, "c.dwg")):
            pytest.skip("dxf2dwg no pudo generar el DWG de prueba")
        datos = open(os.path.join(d, "c.dwg"), "rb").read()
    finally:
        shutil.rmtree(d)
    antes = _temporales()
    p = leer_pieza(datos, "caja.dwg")
    assert p.volumen_mm3 == pytest.approx(24000, rel=1e-2)
    assert _temporales() == antes
