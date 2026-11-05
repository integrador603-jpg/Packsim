# ─── Etapa 1: compila el conversor de DWG (LibreDWG, GPL; se usa como programa aparte) ───
FROM python:3.13-slim AS libredwg
ARG LIBREDWG_VERSION=0.13.3
RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl xz-utils ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL "https://github.com/LibreDWG/libredwg/releases/download/${LIBREDWG_VERSION}/libredwg-${LIBREDWG_VERSION}.tar.xz" | tar xJ \
    && cd "libredwg-${LIBREDWG_VERSION}" \
    && ./configure --disable-bindings --disable-static --prefix=/opt/libredwg >/dev/null \
    && make -j"$(nproc)" >/dev/null && make install >/dev/null \
    && /opt/libredwg/bin/dwg2dxf --version

# ─── Etapa 2: aplicación ───
FROM python:3.13-slim
# librerías de sistema que necesita OpenCascade (lectura de STEP/IGES)
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libx11-6 libexpat1 libxrender1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=libredwg /opt/libredwg /opt/libredwg
ENV PATH="/opt/libredwg/bin:${PATH}" \
    LD_LIBRARY_PATH="/opt/libredwg/lib" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY packsim ./packsim
COPY api ./api
COPY web ./web

# usuario sin privilegios; los archivos temporales de los conversores van a /tmp y se borran siempre
RUN useradd --create-home --uid 10001 packsim
USER packsim

EXPOSE 8000
# UN solo proceso de uvicorn: los trabajos viven en su memoria (para varias réplicas, pasar el almacén a Redis).
CMD ["sh", "-c", "uvicorn api.app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips='*' --no-server-header"]
