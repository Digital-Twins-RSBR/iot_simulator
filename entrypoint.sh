#!/bin/sh
set -e

# Entrypoint padrão do iot_simulator
# Ordem: copy .env -> ensure config -> restore db (if helper) -> migrate -> collectstatic -> wait TB -> rename -> start sender

ENV_FILE="/iot_simulator/.env"
ENV_EXAMPLE="/iot_simulator/.env.example"

# Copia .env se necessário
if [ ! -f "$ENV_FILE" ] && [ -f "$ENV_EXAMPLE" ]; then
	echo ".env não existe -> copiando de .env.example"
	cp "$ENV_EXAMPLE" "$ENV_FILE"
fi

# Garante THINGSBOARD_HOST correto
if [ -f "$ENV_FILE" ] && grep -q '^THINGSBOARD_HOST=' "$ENV_FILE" 2>/dev/null; then
		# Use Python to reliably replace the key in-place (some mounts don't support sed -i atomic rename)
		# pass the target path as an arg so we don't need to interpolate into the heredoc
		python3 - "$ENV_FILE" <<'PY'
import sys
p = sys.argv[1]
try:
	with open(p, 'r', encoding='utf-8') as f:
		lines = f.readlines()
except FileNotFoundError:
	lines = []
found = False
for i,l in enumerate(lines):
	if l.startswith('THINGSBOARD_HOST='):
		lines[i] = 'THINGSBOARD_HOST=http://10.0.0.11:8080\n'
		found = True
if not found:
	lines.append('THINGSBOARD_HOST=http://10.0.0.11:8080\n')
with open(p, 'w', encoding='utf-8') as f:
	f.writelines(lines)
PY
else
	echo "THINGSBOARD_HOST=http://10.0.0.11:8080" >> "$ENV_FILE"
fi

# Garante usuário/senha padrão
if ! grep -q '^THINGSBOARD_USER=' "$ENV_FILE" 2>/dev/null; then
	echo "THINGSBOARD_USER=tenant@thingsboard.org" >> "$ENV_FILE"
fi
if ! grep -q '^THINGSBOARD_PASSWORD=' "$ENV_FILE" 2>/dev/null; then
	echo "THINGSBOARD_PASSWORD=tenant" >> "$ENV_FILE"
fi

# Garante SECRET_KEY
if ! grep -q '^SECRET_KEY=' "$ENV_FILE" 2>/dev/null; then
	SECRET_KEY=$(openssl rand -base64 48 | tr -d '\n' | tr -d '=+/')
	echo "SECRET_KEY=$SECRET_KEY" >> "$ENV_FILE"
fi

# Exporta variáveis relevantes
if [ -f "$ENV_FILE" ]; then
	export $(grep '^THINGSBOARD_' "$ENV_FILE" | xargs) || true
	export SECRET_KEY=$(grep '^SECRET_KEY=' "$ENV_FILE" | cut -d'=' -f2-) || true
fi

# Corrige DJANGO_SETTINGS_MODULE se necessário
if [ "${DJANGO_SETTINGS_MODULE}" = "iot_simulator.settings" ]; then
	export DJANGO_SETTINGS_MODULE=iot_simulator.settings
fi

# Se não houver POSTGRES_HOST, usa sqlite e restaura DB
if [ -z "${POSTGRES_HOST:-}" ]; then
	DBFILE="/iot_simulator/db.sqlite3"
	DBDIR="$(dirname "$DBFILE")"
	mkdir -p "$DBDIR" || true
	if [ ! -f "$DBFILE" ]; then
		touch "$DBFILE" || true
		echo "[entrypoint] Criado arquivo sqlite em $DBFILE"
	fi
	chmod 666 "$DBFILE" || true
	chmod 777 "$DBDIR" || true
	echo "[entrypoint] Usando sqlite3 local: $DBFILE (perms ajustadas)"
	if [ -x "/iot_simulator/restore_db.sh" ]; then
		echo "[entrypoint] Found restore_db.sh -> running restore helper"
		# If we already restored recently, skip restore unless RESET_SIM_DB is explicitly set
		if [ -f "/iot_simulator/.last_restore" ] && [ "${RESET_SIM_DB:-0}" != "1" ]; then
			echo "[entrypoint] .last_restore found -> skipping restore (to force restore set RESET_SIM_DB=1)"
		else
			if [ "${RESET_SIM_DB:-0}" = "1" ]; then
				/bin/sh /iot_simulator/restore_db.sh --force-reset || echo "[entrypoint] restore_db.sh failed (continuing)"
			else
				/bin/sh /iot_simulator/restore_db.sh || echo "[entrypoint] restore_db.sh failed (continuing)"
			fi
		fi
	fi
else
	echo "[entrypoint] POSTGRES_HOST definido -> usando PostgreSQL."
fi

# Re-export THINGSBOARD_* after potential restore
if [ -f "/iot_simulator/.env" ]; then
	export $(grep '^THINGSBOARD_' /iot_simulator/.env | xargs) || true
fi

echo "Aplicando migrações..."
python manage.py migrate --noinput

echo "Coletando arquivos estáticos..."
python manage.py collectstatic --noinput || true

# Aguardar o ThingsBoard estar acessível antes de renomear e iniciar telemetria
echo "Aguardando ThingsBoard responder no endpoint /api/auth/login..."
# hardcoded IP conforme convenção do projeto
TB_URL="http://10.0.0.11:8080/api/auth/login"
# Try briefly for ThingsBoard; if still unreachable, continue and let send_telemetry
# do the active reconciliation/retry. This avoids simulators stuck forever when network
# to TB is temporarily unavailable.
MAX_WAIT=30
WAITED=0
# arquivos temporários para resposta/erro do curl
TMP_OUT=$(mktemp /tmp/tb_resp.XXXXXX 2>/dev/null || echo "/tmp/tb_resp_$$")
TMP_ERR=$(mktemp /tmp/tb_err.XXXXXX 2>/dev/null || echo "/tmp/tb_err_$$")
while true; do
	# faz request e captura status + possíveis mensagens de erro
	STATUS=$(curl -sS -o "$TMP_OUT" -w "%{http_code}" --connect-timeout 2 --max-time 5 -X POST "$TB_URL" -H 'Content-Type: application/json' -d '{"username":"tenant@thingsboard.org","password":"tenant"}' 2>"$TMP_ERR" || true)
	CURL_RC=$?
	BODY=$(cat "$TMP_OUT" 2>/dev/null || echo "")
	ERR_OUTPUT=$(cat "$TMP_ERR" 2>/dev/null || echo "")
	# Log resumido com amostra do corpo para depuração (máx 200 chars)
	echo "[entrypoint][wait-for] curl_rc=$CURL_RC http_status=$STATUS body_sample='$(printf "%.200s" "$BODY")' stderr_sample='$(printf "%.200s" "$ERR_OUTPUT")'"

	if [ "$STATUS" = "200" ] || [ "$STATUS" = "400" ] || [ "$STATUS" = "401" ]; then
		echo "[entrypoint] ThingsBoard respondeu em $TB_URL (HTTP $STATUS). Corpo: $(printf "%.200s" "$BODY")"
		break
	else
		echo "[entrypoint][wait-for] Ainda sem resposta do ThingsBoard (HTTP $STATUS). Aguarda 3s... ($WAITED/$MAX_WAIT s)"
		if [ $CURL_RC -ne 0 ]; then
			echo "[entrypoint][wait-for][curl-error] rc=$CURL_RC stderr='$(printf "%.200s" "$ERR_OUTPUT")'"
		fi
		sleep 3
		WAITED=$((WAITED+3))
		if [ $WAITED -ge $MAX_WAIT ]; then
			echo "[entrypoint][ERRO] ThingsBoard não respondeu após $MAX_WAIT segundos. Último http_status=$STATUS; mostrando saída de debug:" 
			echo "--- stderr ---"
			cat "$TMP_ERR" 2>/dev/null || true
			echo "--- body ---"
			cat "$TMP_OUT" 2>/dev/null || true
			break
		fi
	fi
done
rm -f "$TMP_OUT" "$TMP_ERR" >/dev/null 2>&1 || true

# Determina número do simulador (env ou arg)
SIMULATOR_NUMBER="${SIMULATOR_NUMBER:-1}"
if [ -n "$1" ]; then
	SIMULATOR_NUMBER="$1"
fi

echo "Renomeando devices para este simulador $SIMULATOR_NUMBER..."
python manage.py rename_devices_for_simulator --sim "$SIMULATOR_NUMBER" || echo "[entrypoint][WARN] Falha ao renomear devices."

# Configura token do InfluxDB (opcional) via env
if [ -n "$INFLUXDB_TOKEN" ]; then
	echo "INFLUXDB_TOKEN definido (****)."
else
	echo "INFLUXDB_TOKEN não definido. Escrita no Influx pode falhar."
fi

RANDOMIZE_FLAG="--randomize"
MEMORY_FLAG="--memory"
if [ "${RANDOMIZE:-1}" = "0" ]; then
	RANDOMIZE_FLAG=""
fi
if [ "${USE_MEMORY_STATE:-1}" = "0" ]; then
	MEMORY_FLAG=""
fi

echo "Comando: python manage.py send_telemetry ${RANDOMIZE_FLAG} ${MEMORY_FLAG}"
# If this is simulator 1, start a simple HTTP server on 0.0.0.0:8001 in background so the
# container exposes port 8001 for external access. Keep telemetry sender in foreground.
if [ "${SIMULATOR_NUMBER:-1}" = "1" ]; then
	echo "[entrypoint] SIMULATOR_NUMBER=1 -> starting HTTP server on 0.0.0.0:8001 in background"
	# Use Django runserver as a lightweight HTTP server; redirect logs to /var/log/sim_http_8001.log
	# POSIX-safe redirection and background handling (avoid bash-only &> and '& ||' syntax)
	mkdir -p /var/log || true
	python manage.py runserver 0.0.0.0:8001 >/var/log/sim_http_8001.log 2>&1 &
	RUNSV_PID=$!
	# give it a moment to start and verify the process is alive
	sleep 1
	if ! kill -0 "$RUNSV_PID" 2>/dev/null; then
		echo "[entrypoint][WARN] failed to start HTTP server (pid $RUNSV_PID)"
	else
		echo "[entrypoint] HTTP server started (pid $RUNSV_PID)"
	fi
fi
echo "Iniciando simulador: enviando telemetria (send_telemetry)..."
exec python manage.py send_telemetry ${RANDOMIZE_FLAG} ${MEMORY_FLAG}
