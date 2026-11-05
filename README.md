# Packsim: motor de embalaje

Calcula cómo acomodar piezas en un embalaje, cuántas entran como máximo, la **saturación por capacidad** y el **peso bruto**.
Es la etapa 1 del proyecto: el motor en Python, sin interfaz ni servidor. Las etapas 2 a 5 (API, interfaz web, física y despliegue) lo usan sin modificarlo.

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

## Próximas etapas

2. API sin estado (FastAPI): subís el archivo, recibís el resultado, nada se guarda.
3. Interfaz web (la de la maqueta) conectada a la API, con descarga de imagen y JSON.
4. Física en el servidor con PyBullet (volcado a granel y validación con vibración).
5. Despliegue en Railway con Dockerfile y tests automáticos.
