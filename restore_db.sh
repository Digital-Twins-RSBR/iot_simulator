#!/bin/sh
# Wrapper to prepare sqlite DB and invoke the Django management command restore_db
set -e

BASE_DIR="/iot_simulator"
SRC_DB="$BASE_DIR/initial_data/db.sqlite3"
TARGET_DB_CONF_PATH="$BASE_DIR/db.sqlite3"

echo "[restore_db.sh] preparando ambiente de restore"
FORCE=0
for arg in "$@"; do
  case "$arg" in
    --force|--force-reset)
      FORCE=1
      ;;
  esac
done
mkdir -p "$(dirname "$TARGET_DB_CONF_PATH")" || true
if [ ! -f "$SRC_DB" ]; then
  echo "[restore_db.sh] template $SRC_DB não encontrado; nada a restaurar"
  exit 0
fi

echo "[restore_db.sh] chamando python manage.py restore_db --keep-current-backup"
if [ "$FORCE" -eq 1 ]; then
  echo "[restore_db.sh] force mode: removing existing target DB if present"
  rm -f "$TARGET_DB_CONF_PATH" || true
fi
cd "$BASE_DIR" || true
python manage.py restore_db --keep-current-backup || {
  echo "[restore_db.sh] restore_db falhou" >&2
  exit 1
}
date -u +"%Y%m%d%H%M%S" > "$BASE_DIR/.last_restore"
echo "[restore_db.sh] restore concluído"
