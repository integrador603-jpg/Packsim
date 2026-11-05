# Despliegue en Railway

Railway construye la imagen con el `Dockerfile` del repositorio y vuelve a desplegar sola cada vez que se actualiza `main`.

## Primera vez

1. **Entrá a [railway.com](https://railway.com)** con tu cuenta de GitHub.
2. **New Project → Deploy from GitHub repo → Packsim.**
   Si el repositorio no aparece, tocá *Configure GitHub App* y dale acceso a `Packsim`.
3. **Esperá la primera construcción.** Tarda entre 5 y 10 minutos porque compila el conversor de DWG. Las siguientes son más rápidas.
4. **Cargá las variables** (servicio → *Variables*):

   | Variable | Valor |
   |---|---|
   | `PACKSIM_CLAVE` | La contraseña para entrar. Usá una larga (15 caracteres o más) |
   | `PACKSIM_SECRETO` | Un valor aleatorio largo para firmar las sesiones. Generalo con `python -c "import secrets; print(secrets.token_hex(32))"` |

   Opcionales, si el plan tiene poca memoria: `PACKSIM_TRABAJOS_PARALELOS=1` y `PACKSIM_MEMORIA_MAX_MB=1536`.
   El resto de las variables está en el README.
5. **Generá la dirección pública:** servicio → *Settings* → *Networking* → *Generate Domain*. Queda algo como `packsim-production.up.railway.app`.
6. **Abrí la dirección**, ingresá la contraseña y probá con una pieza del catálogo.

## Actualizaciones

Cada merge a `main` dispara un nuevo despliegue. Railway espera a que `/salud` responda antes de pasar el tráfico a la versión nueva; si falla, queda la anterior funcionando.

Los tests corren solos en GitHub (pestaña *Actions*) en cada pull request. No hagas merge si están en rojo.

## Seguridad

- **Nunca** pongas la contraseña ni el secreto en el código: solo en las variables de Railway.
- Dejá el repositorio **privado**.
- Para cambiar la contraseña, cambiá `PACKSIM_CLAVE` y redesplegá. Si además cambiás `PACKSIM_SECRETO`, se cierran todas las sesiones abiertas.

## Costo y recursos

- En reposo usa unos 300 MB de memoria. Mientras calcula, cada simulación puede usar hasta `PACKSIM_MEMORIA_MAX_MB`.
- Con el plan Hobby de Railway (unos 5 USD por mes con uso incluido, verificá el precio vigente en su página) alcanza para uso personal o de un equipo chico.
- Dejá **una sola réplica**: los trabajos viven en la memoria del servidor. Para escalar a varias réplicas hay que pasar el almacén de trabajos a Redis (ver `api/trabajos.py`).

## Si algo falla

| Síntoma | Qué revisar |
|---|---|
| La construcción falla en "libredwg" | Railway no pudo descargar LibreDWG de GitHub: reintentá el despliegue |
| El despliegue queda en "Healthcheck failed" | *Deploy Logs*: casi siempre es una variable mal cargada |
| La página pide contraseña y no entra | Revisá `PACKSIM_CLAVE`; no tiene que tener espacios al principio ni al final |
| "Llegaste al máximo de simulaciones por hora" | Subí `PACKSIM_LIMITE_POR_HORA` |
| Las simulaciones de piezas grandes se cancelan | Subí `PACKSIM_TIEMPO_MAX_S` o `PACKSIM_MEMORIA_MAX_MB`, o exportá la pieza con menos detalle |
