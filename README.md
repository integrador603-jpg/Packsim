# Packsim: motor de embalaje

Calcula cómo acomodar piezas en un embalaje, cuántas entran como máximo, la **saturación por capacidad** y el **peso bruto**.
El repositorio tiene el motor en Python (etapa 1), la API web sin estado (etapa 2) y la interfaz web (etapa 3). Las etapas siguientes (física y despliegue) los usan sin modificarlos.

## Qué hace

| Módulo | Función |
|---|---|
| `catalogo.py` | Minutería normalizada como sólidos 3D con su peso: tornillo hexagonal (ISO 4017), Allen (ISO 4762), tuerca (ISO 4032), autofrenante (DIN 985), arandela plana (ISO 7089), grower (DIN 127 B), varilla (DIN 975), buje a medida y rodamientos 6201–6208 |
| `lectura.py` | Lee STEP, IGES, STL, OBJ, GLB, DXF 3D y DWG **sin guardar el archivo**: todo en memoria y, si un conversor necesita disco, en una carpeta temporal que se borra siempre |
| `empaque.py` | Estrategias de acomodo: grilla simple, bloques mixtos, tresbolillo (piezas redondas) y cabeza-cola (tornillos) |
| `motor.py` | `simular()` elige la mejor según la prioridad, aplica los límites de peso y arma el resultado (contrato JSON v1) |

## Definiciones

- **Saturación** = piezas que van ÷ máximo de piezas que entran físicamente. Una pieza hueca puede estar al 100% con poco volumen ocupado.
- **El peso no es saturación**, es un límite que se informa aparte (`limitado_por`).
- **Peso bruto** = piezas + embalaje vacío (tara) + relleno.
- **Manipulación manual**: el límite se controla sobre el peso bruto. Con **autoelevador** solo cuenta la carga máxima del embalaje.

## Uso

```bash
pip install -e ".[test]"

# catálogo disponible (familias, campos, materiales)
python -m packsim catalogo

# pieza del catálogo
python -m packsim simular --familia tornillo_hexagonal --valor metrica=M10 --valor largo=50 \
    --caja 300 200 150 --carga-max 15 --tara 0.3

# archivo 3D (peso real opcional; si no, material × volumen)
python -m packsim simular --archivo pieza.step --peso 3.7 --caja 600 400 300 --carga-max 30 --tara 1.1
```

Desde Python:

```python
from packsim.catalogo import construir
from packsim.modelos import Embalaje, Criterios
from packsim.motor import simular

pieza = construir("tornillo_hexagonal", {"metrica": "M10", "largo": 50})
r = simular(pieza, Embalaje((300, 200, 150), "carton", carga_max_kg=15, tara_kg=0.3), Criterios())
r["resultado"]["saturacion"], r["resultado"]["peso_bruto_kg"]
```

## Contrato de salida (v1)

`simular()` devuelve un diccionario serializable con `pieza`, `embalaje`, `criterios` y `resultado`. En `resultado`:

- `piezas`, `maximo_posible`, `saturacion`, `limitado_por`, `limite_por_peso`
- `peso_piezas_kg`, `peso_bruto_kg`, `peso_bruto_detalle_kg`, `volumen_ocupado`
- `alternativas` (cada estrategia con sus piezas y orientaciones), `explicacion`, `capas`
- `disposicion`: centro y rotación de cada pieza, ordenada de abajo hacia arriba

Marco del embalaje: origen en la esquina interior inferior; x largo, y ancho, z alto.
`p_embalaje = rotacion · (p_pieza − centro_envolvente_mm) + centro_mm`.

## API (etapa 2)

Servicio sin estado: recibe la pieza, calcula y devuelve el resultado. **Ningún archivo 3D se guarda.**

```bash
PACKSIM_CLAVE="una-contraseña-larga" PACKSIM_SECRETO="$(openssl rand -hex 32)" uvicorn api.app:app --port 8000
```

| Método | Ruta | Qué hace |
|---|---|---|
| POST | `/v1/sesion` | Inicia sesión con `{"clave": "..."}` (cookie firmada, `HttpOnly`, `SameSite=Strict`) |
| GET | `/v1/catalogo` | Piezas, materiales, embalajes de referencia y formatos aceptados |
| GET | `/v1/embalajes/tara?largo=&ancho=&alto=&tipo=` | Tara estimada de un embalaje a medida |
| POST | `/v1/piezas` | Analiza solo la pieza (ficha y malla para la vista previa) → `202` con el `id` |
| POST | `/v1/simulaciones` | Multipart: `parametros` (JSON) y `archivo` opcional → `202` con el `id` |
| GET | `/v1/trabajos/{id}` | Estado (`en_cola`, `procesando`, `listo`, `error`) y resultado |
| GET | `/v1/trabajos/{id}/malla` | La pieza en GLB liviano para dibujarla en el visor |
| DELETE | `/v1/trabajos/{id}` | Borra el resultado antes de que venza |

Ejemplo de `parametros`:

```json
{"pieza": {"origen": "catalogo", "familia": "tornillo_hexagonal", "valores": {"metrica": "M10", "largo": 50}},
 "embalaje": {"interior_mm": [300, 200, 150], "tipo": "carton", "carga_max_kg": 15, "tara_kg": 0.3},
 "criterios": {"manipulacion": "manual", "peso_bruto_manipulable_kg": 15, "prioridad": "cantidad"}}
```

Para un archivo: `"pieza": {"origen": "archivo", "unidades": "mm", "peso_kg": 3.7}` y el archivo en el campo `archivo`.
Para integraciones se usa `Authorization: Bearer <clave>` con las claves de `PACKSIM_API_KEYS`.

**Cómo protege los datos**

- El archivo se lee en memoria; los conversores usan una carpeta temporal que se borra siempre.
- Cada simulación corre en un **proceso aparte** con tiempo y memoria máximos: un archivo dañado no tumba el servidor.
- Los resultados viven en memoria y **vencen a la hora**. En los logs solo queda la huella del archivo, nunca el nombre ni el contenido.
- Límite de tamaño de archivo y de simulaciones por hora por IP; demora ante contraseñas incorrectas.

**Variables de entorno**

| Variable | Defecto | Uso |
|---|---|---|
| `PACKSIM_CLAVE` | — | Contraseña de la interfaz. Sin ella (y sin API keys) la API queda abierta: solo para uso local |
| `PACKSIM_SECRETO` | aleatorio | Firma de las sesiones. Fijalo en producción para que las sesiones sobrevivan a un reinicio |
| `PACKSIM_API_KEYS` | — | Claves para integraciones, separadas por coma |
| `PACKSIM_TAMANO_MAX_MB` | 50 | Tamaño máximo de archivo |
| `PACKSIM_TIEMPO_MAX_S` | 120 | Tiempo máximo por simulación |
| `PACKSIM_MEMORIA_MAX_MB` | 2048 | Memoria máxima por simulación |
| `PACKSIM_TRABAJOS_PARALELOS` | 2 | Simulaciones simultáneas |
| `PACKSIM_VENCIMIENTO_S` | 3600 | Cuánto dura un resultado en memoria |
| `PACKSIM_LIMITE_POR_HORA` | 120 | Simulaciones por hora por IP |
| `PACKSIM_COOKIES_SEGURAS` | 1 | Poné 0 solo para probar en `http://localhost` |

**Escala:** el estado de los trabajos vive en la memoria de un solo servidor. Para varias réplicas se reemplaza `Almacen` (en `api/trabajos.py`) por una versión con Redis; el resto no cambia.

## Interfaz web (etapa 3)

La API sirve la interfaz en `/` (carpeta `web/`). Flujo en 4 pasos: pieza (catálogo o archivo 3D), embalaje, criterios y resultado.

- Toda la geometría y los cálculos vienen de la API; el navegador solo dibuja.
- El archivo 3D se envía para analizarlo y otra vez al calcular, y nunca queda guardado en el servidor.
- Resultado: saturación, factor limitante, peso bruto con su desglose, alternativas, explicación, armado por capas y vista 3D con caja de cartón, madera o plástico, transparencia y corte por altura.
- Descargas: **imagen** del acomodo con los datos clave al pie y **resultado** en JSON (contrato v1).
- Sin scripts incrustados: la API envía una política de contenido (CSP) que solo permite los scripts propios y los de cdnjs/jsdelivr.

Probar local: `PACKSIM_CLAVE=prueba PACKSIM_COOKIES_SEGURAS=0 uvicorn api.app:app` y abrir http://localhost:8000.

## Requisitos

- Python 3.10+
- Para DWG: `dwg2dxf` de [LibreDWG](https://www.gnu.org/software/libredwg/) en el `PATH` (o la variable `PACKSIM_DWG2DXF`).
  Se ejecuta como programa aparte, con tiempo límite. LibreDWG es GPL: usarlo en un servidor no impone obligaciones; distribuir un instalable sí.

## Tests

```bash
pytest
```

Verifican pesos contra tablas, conteos exactos, **cero colisiones** entre piezas (colisión exacta de mallas con FCL), que todo quede dentro del embalaje, límites de peso y tara, lectura de STEP en pulgadas y de DWG, y que no queden archivos temporales.

## Limitaciones conocidas

- La rosca no se modela: el peso de tornillos y tuercas queda unos pocos por ciento arriba del real.
- Las piezas leídas de archivos se acomodan por su caja envolvente. Encastres entre piezas de archivo (pares, anidado) llegan en una etapa posterior.
- El modo **a granel** necesita la simulación física (etapa 4) y hoy devuelve un error explicativo.

## Prototipo

`prototipo/packsim_maqueta.html` es la maqueta funcional que define el flujo y las pantallas (corre sola en el navegador). Es la referencia para la interfaz de la etapa 3; la física a granel de la maqueta no es confiable con piezas chicas y se reemplaza por la del servidor.

## Despliegue

Ver [DESPLIEGUE.md](DESPLIEGUE.md): Railway con el `Dockerfile` del repositorio, tests automáticos en GitHub Actions.

## Próximas etapas

4. Física en el servidor con PyBullet (volcado a granel y validación con vibración).
