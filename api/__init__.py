"""API de Packsim."""
import os

# Las librerías numéricas abren un hilo por núcleo del servidor; acá no aportan (cada simulación
# corre en su propio proceso) y en servidores con muchos núcleos desperdician memoria.
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, "1")
os.environ.setdefault("MALLOC_ARENA_MAX", "2")
