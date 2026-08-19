# Backend image: Django + DRF served by gunicorn.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install build deps for psycopg2, then Python requirements.
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure the entrypoint is executable regardless of the host's file mode
# (a file copied without its execute bit would otherwise fail to exec).
RUN chmod +x ./entrypoint.sh

EXPOSE 8000
# Invoke via sh so a missing execute bit can never block startup.
ENTRYPOINT ["sh", "./entrypoint.sh"]
