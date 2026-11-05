"""Funciones auxiliares que corren en el proceso aislado durante los tests."""
import time


def lento(conn, params, datos, nombre, memoria_mb):
    time.sleep(30)
    conn.send({"ok": True})


def revienta(conn, params, datos, nombre, memoria_mb):
    import os
    os._exit(1)


def gloton(conn, params, datos, nombre, memoria_mb):
    bloques = []
    for _ in range(40):
        bloques.append(bytearray(25 * 1024 * 1024))   # 25 MB reales por vuelta
        for i in range(0, len(bloques[-1]), 4096):
            bloques[-1][i] = 1
        time.sleep(0.05)
    conn.send({"ok": True})


def sin_limite_de_reserva(conn, params, datos, nombre, memoria_mb):
    import resource
    conn.send({"ok": True, "as": resource.getrlimit(resource.RLIMIT_AS)[0] == resource.RLIM_INFINITY})


def aborta(conn, params, datos, nombre, memoria_mb):
    import os, signal
    os.kill(os.getpid(), signal.SIGABRT)
