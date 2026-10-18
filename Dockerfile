# PORTUS Fase 2 — imagen única para portus-web, portus-puente y portus-msg.
# Cada servicio de docker-compose.yml la usa con un comando distinto.
# Probada para linux/arm64 (Raspberry Pi 4B con Raspberry Pi OS de 64 bits)
# y linux/amd64 (PC). Guía completa en docs/docker.md.
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp

WORKDIR /app

# Solo las dependencias de ejecución: ruff, mypy y pytest son de desarrollo (CI)
# y en la Raspberry solo ocupan espacio. Todas tienen rueda precompilada para
# arm64 y amd64, así que no hace falta compilador.
COPY requirements.txt .
RUN grep -vE '^(ruff|mypy|pytest)==' requirements.txt > requisitos_ejecucion.txt \
    && pip install -r requisitos_ejecucion.txt \
    && rm requisitos_ejecucion.txt

# El código va dentro de la imagen; config/ y db/ se montan desde el host
# (docker-compose.yml), así los secretos y la base nunca quedan en la imagen.
COPY puente/ puente/
COPY web/ web/
COPY mensajeria/ mensajeria/
COPY herramientas/ herramientas/
COPY db/esquema.sql db/esquema.sql
COPY db/migraciones/ db/migraciones/

# El usuario lo fija docker-compose.yml (PORTUS_UID/PORTUS_GID) para que pueda
# escribir db/ del host; el comando también lo fija cada servicio.
CMD ["python", "-m", "web", "--config", "config/portus.env"]
