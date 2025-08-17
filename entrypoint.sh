#!/bin/sh
set -e

## Carrega .env se existir ou copia de .env.example
ENV_FILE="/iot_simulator/.env"
ENV_EXAMPLE="/iot_simulator/.env.example"
if [ ! -f "$ENV_FILE" ] && [ -f "$ENV_EXAMPLE" ]; then
	echo ".env não existe -> copiando de .env.example"
	cp "$ENV_EXAMPLE" "$ENV_FILE"
fi

# Carrega .env de forma robusta, exportando cada variável
if [ -f "$ENV_FILE" ]; then
	echo "Carregando variáveis de $ENV_FILE"
	set -a
	. "$ENV_FILE"
	set +a
fi

# Corrige DJANGO_SETTINGS_MODULE se antigo nome estiver presente
if [ "${DJANGO_SETTINGS_MODULE}" = "iot_simulator.settings" ]; then
	export DJANGO_SETTINGS_MODULE=iot_simulator.settings
fi

# Permite adiar inicialização completa quando usado em topologia (Containernet)
if [ "${DEFER_START:-0}" = "1" ]; then
	echo "[entrypoint] DEFER_START=1 -> aguardando start externo (tail infinito)"
	tail -f /dev/null
fi

# Garante que SECRET_KEY exista no .env e no ambiente
if [ -z "$ENV_FILE" ]; then ENV_FILE="/iot_simulator/.env"; fi
if ! grep -q '^SECRET_KEY=' "$ENV_FILE" 2>/dev/null; then
	SECRET_KEY=$(openssl rand -base64 48 | tr -d '\n' | tr -d '=+/')
	echo "SECRET_KEY=$SECRET_KEY" >> "$ENV_FILE"
	echo "[entrypoint] SECRET_KEY gerado e adicionado ao .env"
else
	SECRET_KEY=$(grep '^SECRET_KEY=' "$ENV_FILE" | cut -d'=' -f2-)
fi
export SECRET_KEY

# Ajusta ALLOWED_HOSTS dinamicamente se não definido
if ! grep -q '^ALLOWED_HOSTS=' "$ENV_FILE" 2>/dev/null; then
	HOST_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
	echo "ALLOWED_HOSTS=localhost,127.0.0.1,$HOST_IP,*" >> "$ENV_FILE"
	export ALLOWED_HOSTS="localhost,127.0.0.1,$HOST_IP,*"
fi

# Garante variáveis do ThingsBoard e Influx padrões para o simulator
if ! grep -q '^THINGSBOARD_HOST=' "$ENV_FILE" 2>/dev/null; then
	# host do ThingsBoard usado pela topologia: 10.0.0.11:8080
	echo "THINGSBOARD_HOST=http://10.0.0.11:8080" >> "$ENV_FILE"
	export THINGSBOARD_HOST="http://10.0.0.11:8080"
else
	export THINGSBOARD_HOST="$(grep '^THINGSBOARD_HOST=' "$ENV_FILE" | cut -d'=' -f2-)"
fi

if ! grep -q '^INFLUXDB_HOST=' "$ENV_FILE" 2>/dev/null; then
	echo "INFLUXDB_HOST=10.10.2.20" >> "$ENV_FILE"
	export INFLUXDB_HOST="10.10.2.20"
else
	export INFLUXDB_HOST="$(grep '^INFLUXDB_HOST=' "$ENV_FILE" | cut -d'=' -f2-)"
fi

if ! grep -q '^INFLUXDB_TOKEN=' "$ENV_FILE" 2>/dev/null; then
	echo "INFLUXDB_TOKEN=token" >> "$ENV_FILE"
	export INFLUXDB_TOKEN="token"
else
	export INFLUXDB_TOKEN="$(grep '^INFLUXDB_TOKEN=' "$ENV_FILE" | cut -d'=' -f2-)"
fi
# Se POSTGRES_HOST não estiver definido, assumimos sqlite3 local e garantimos
# que o arquivo e diretório existam e sejam graváveis para evitar
# 'unable to open database file' durante as migrations.
if [ -z "${POSTGRES_HOST:-}" ]; then
	DBFILE="/iot_simulator/db.sqlite3"
	DBDIR="$(dirname "$DBFILE")"
	mkdir -p "$DBDIR" || true
	if [ ! -f "$DBFILE" ]; then
		touch "$DBFILE" || true
		echo "[entrypoint] Criado arquivo sqlite em $DBFILE"
	fi
	# Permissões amplas apenas para ambiente de desenvolvimento/containernet
	chmod 666 "$DBFILE" || true
	chmod 777 "$DBDIR" || true
	echo "[entrypoint] Usando sqlite3 local: $DBFILE (perms ajustadas)"
else
	echo "[entrypoint] POSTGRES_HOST definido -> usando PostgreSQL. Nota: psycopg é necessário no container para checagens/uso de Postgres."
fi

echo "Aplicando migrações..."
python manage.py migrate --noinput

echo "Coletando arquivos estáticos..."
python manage.py collectstatic --noinput || true

# Configura token do InfluxDB (opcional) via env
if [ -n "$INFLUXDB_TOKEN" ]; then
	echo "INFLUXDB_TOKEN definido (****)."
else
	echo "INFLUXDB_TOKEN não definido. Escrita no Influx pode falhar."
fi

echo "Iniciando simulador: enviando telemetria (send_telemetry) em vez de Gunicorn..."
# Por padrão rodamos o comando de telemetria do simulator com leituras randomicas.
# Use VARS para ajustar se desejar: por exemplo, para desabilitar randomize, exporte RANDOMIZE=0
RANDOMIZE_FLAG="--randomize"
MEMORY_FLAG="--memory"
if [ "${RANDOMIZE:-1}" = "0" ]; then
	RANDOMIZE_FLAG=""
fi
if [ "${USE_MEMORY_STATE:-1}" = "0" ]; then
	MEMORY_FLAG=""
fi

echo "Comando: python manage.py send_telemetry ${RANDOMIZE_FLAG} ${MEMORY_FLAG}"
exec python manage.py send_telemetry ${RANDOMIZE_FLAG} ${MEMORY_FLAG}
