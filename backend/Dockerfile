FROM python:3.13-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        postgresql-client && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /srv/backend

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY migrations/ ./migrations/
COPY alembic.ini .

RUN useradd -u 10001 -U -s /bin/sh sanctum && \
    mkdir -p /data /secrets && \
    chown -R sanctum:sanctum /data /secrets

USER sanctum

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
