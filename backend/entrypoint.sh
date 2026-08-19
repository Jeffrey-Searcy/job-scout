#!/usr/bin/env sh
# Backend container entrypoint: wait for Postgres, apply migrations, seed the
# starter data (idempotent), collect static files, then launch gunicorn.
set -e

echo "Waiting for Postgres at ${DB_HOST:-db}:${DB_PORT:-5432}..."
until python -c "import socket,os,sys; s=socket.socket(); s.settimeout(2); s.connect((os.environ.get('DB_HOST','db'), int(os.environ.get('DB_PORT','5432')))); s.close()" 2>/dev/null; do
  sleep 1
done
echo "Postgres is up."

python manage.py migrate --noinput
# Optional demo data only when explicitly requested (keeps real installs empty).
if [ "${SEED_SAMPLE:-0}" = "1" ]; then
  python manage.py seed_data
fi
python manage.py collectstatic --noinput

exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3
