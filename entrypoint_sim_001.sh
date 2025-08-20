
#!/bin/sh
set -e

# Wrapper: delega para entrypoint padrão passando o número do simulador
SIM_NUMBER="1"
if [ -n "$1" ]; then
  SIM_NUMBER="$1"
fi

echo "Delegando ao entrypoint padrão com SIMULATOR_NUMBER=$SIM_NUMBER"
export SIMULATOR_NUMBER="$SIM_NUMBER"
exec /bin/sh /iot_simulator/entrypoint.sh "$SIM_NUMBER"
