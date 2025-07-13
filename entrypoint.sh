#!/bin/sh

set -e

echo "Aplicando migrações..."
python manage.py migrate --noinput

echo "Iniciando Listen..."
python manage.py send_telemetry
