# Farmacia Piedra en internet: la misma aplicación Neji POS, servida por waitress.
# Los datos (neji.db, respaldos y la clave de sesión) viven en el disco montado en /datos.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=America/Santiago \
    NEJI_WEB=1 \
    NEJI_DATOS=/datos \
    PORT=8080

# tzdata: la hora de las ventas, cortes y respaldos es la de Chile, no la del servidor.
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt
COPY run.py .
COPY neji ./neji

EXPOSE 8080
CMD ["python", "run.py", "--web"]
