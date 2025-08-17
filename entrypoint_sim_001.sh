#!/bin/sh
set -e

# Lightweight entrypoint for simulator 001: run Django on port 8001 for testing UI access
ENV_FILE="/iot_simulator/.env"
if [ -f "$ENV_FILE" ]; then
  set -a
  . "$ENV_FILE"
  set +a
fi

# Ensure DJANGO_SETTINGS_MODULE is correct
if [ "${DJANGO_SETTINGS_MODULE}" = "iot_simulator.settings" ]; then
  export DJANGO_SETTINGS_MODULE=iot_simulator.settings
fi

# Ensure SECRET_KEY
if ! grep -q '^SECRET_KEY=' "$ENV_FILE" 2>/dev/null; then
  SECRET_KEY=$(openssl rand -base64 48 | tr -d '\n' | tr -d '=+/')
  echo "SECRET_KEY=$SECRET_KEY" >> "$ENV_FILE"
  export SECRET_KEY
else
  export SECRET_KEY=$(grep '^SECRET_KEY=' "$ENV_FILE" | cut -d'=' -f2-)
fi

# Use sqlite local if POSTGRES_HOST not defined
if [ -z "${POSTGRES_HOST:-}" ]; then
  DBFILE="/iot_simulator/db.sqlite3"
  DBDIR="$(dirname "$DBFILE")"
  mkdir -p "$DBDIR" || true
  if [ ! -f "$DBFILE" ]; then
    touch "$DBFILE" || true
  fi
  chmod 666 "$DBFILE" || true
  chmod 777 "$DBDIR" || true
fi

# Run migrations and start django devserver on port 8001
echo "Aplicando migrações (sim_001)..."
python manage.py migrate --noinput

echo "Coletando estáticos (sim_001)..."
python manage.py collectstatic --noinput || true

echo "Iniciando Django devserver em 0.0.0.0:8001"
exec python manage.py runserver 0.0.0.0:8001
