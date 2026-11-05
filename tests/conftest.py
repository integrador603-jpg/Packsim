import numpy as np
import pytest
import trimesh


def mallas_colocadas(pieza, colocaciones):
    """Mallas de cada pieza en el marco del embalaje."""
    out = []
    c0 = pieza.centro_mm
    for c in colocaciones:
        T = np.eye(4)
        T[:3, :3] = c.rotacion
        T[:3, 3] = c.centro_mm - c.rotacion @ c0
        m = pieza.malla.copy()
        m.apply_transform(T)
        out.append(m)
    return out


def verificar_disposicion(pieza, colocaciones, B, tol=1e-3):
    """Devuelve (colisiones, fuera_de_caja) usando colisión exacta de mallas (FCL)."""
    mallas = mallas_colocadas(pieza, colocaciones)
    fuera = sum(1 for m in mallas if (m.bounds[0] < -tol).any() or (m.bounds[1] > np.array(B) + tol).any())
    cm = trimesh.collision.CollisionManager()
    for i, m in enumerate(mallas):
        cm.add_object(str(i), m)
    choca, pares = cm.in_collision_internal(return_names=True)
    return (len(pares) if choca else 0), fuera


@pytest.fixture
def verificar():
    return verificar_disposicion
