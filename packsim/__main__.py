"""
Línea de comandos de prueba.

  python -m packsim catalogo
  python -m packsim simular --familia tornillo_hexagonal --valor metrica=M10 --valor largo=50 --caja 300 200 150
  python -m packsim simular --archivo pieza.step --peso 3.7 --caja 600 400 300 --carga-max 30 --tara 1.1
"""
import argparse
import json
import sys

from .catalogo import construir, descripcion_catalogo
from .lectura import leer_pieza
from .modelos import Criterios, Embalaje
from .motor import simular


def main(argv=None):
    ap = argparse.ArgumentParser(prog="packsim")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("catalogo")
    s = sub.add_parser("simular")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--familia"); g.add_argument("--archivo")
    s.add_argument("--valor", action="append", default=[], help="campo=valor del catálogo")
    s.add_argument("--material", default="acero")
    s.add_argument("--unidades", default="mm")
    s.add_argument("--peso", type=float, default=None, help="peso unitario real en kg (archivos)")
    s.add_argument("--caja", nargs=3, type=float, required=True, metavar=("LARGO", "ANCHO", "ALTO"))
    s.add_argument("--tipo", default="carton", choices=["carton", "madera", "plastico"])
    s.add_argument("--carga-max", type=float, default=0)
    s.add_argument("--tara", type=float, default=0)
    s.add_argument("--relleno", type=float, default=0)
    s.add_argument("--holgura", type=float, default=1.0)
    s.add_argument("--manipulacion", default="manual", choices=["manual", "autoelevador"])
    s.add_argument("--peso-manual", type=float, default=15.0)
    s.add_argument("--mantener-posicion", action="store_true")
    s.add_argument("--prioridad", default="cantidad", choices=["cantidad", "estabilidad", "picking"])
    s.add_argument("--actuales", type=int, default=0)
    s.add_argument("--con-disposicion", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "catalogo":
        print(json.dumps(descripcion_catalogo(), ensure_ascii=False, indent=2)); return
    if a.familia:
        vals = dict(v.split("=", 1) for v in a.valor)
        pieza = construir(a.familia, vals, a.material)
    else:
        with open(a.archivo, "rb") as fh:
            pieza = leer_pieza(fh.read(), a.archivo, a.unidades, a.material, a.peso)
    emb = Embalaje(tuple(a.caja), a.tipo, carga_max_kg=a.carga_max, tara_kg=a.tara, relleno_kg=a.relleno)
    crit = Criterios(holgura_mm=a.holgura, manipulacion=a.manipulacion, peso_bruto_manipulable_kg=a.peso_manual,
                     mantener_posicion=a.mantener_posicion, prioridad=a.prioridad, piezas_actuales=a.actuales)
    r = simular(pieza, emb, crit, incluir_disposicion=a.con_disposicion)
    json.dump(r, sys.stdout, ensure_ascii=False, indent=2); print()


if __name__ == "__main__":
    main()
