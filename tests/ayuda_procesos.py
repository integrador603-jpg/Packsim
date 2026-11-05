"""Funciones auxiliares que corren en el proceso aislado durante los tests."""
import time


def lento(conn, params, datos, nombre, memoria_mb):
    time.sleep(30)
    conn.send({"ok": True})


def revienta(conn, params, datos, nombre, memoria_mb):
    import os
    os._exit(1)
