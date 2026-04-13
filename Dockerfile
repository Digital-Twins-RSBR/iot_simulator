FROM python:3.12

# Diretório de trabalho
WORKDIR /iot_simulator

# Copia os requirements e instala dependências
COPY requirements/ requirements/

RUN apt-get update && \
    apt-get install -y iproute2 iputils-ping net-tools procps iptables curl tcpdump inetutils-traceroute dnsutils lsof nano less vim socat iperf3 netcat-openbsd && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements/base.txt

# Copia o restante do código
COPY . .

# Expõe a porta HTTP usada pelo entrypoint quando SIMULATOR_NUMBER=1
EXPOSE 8001

ENV DJANGO_SETTINGS_MODULE=iot_simulator.settings_base

# Comando padrão (pode ser sobrescrito)
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
