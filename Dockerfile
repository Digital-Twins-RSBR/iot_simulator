FROM python:3.12

# Diretório de trabalho
WORKDIR /iot_simulator

# Copia os requirements e instala dependências
COPY requirements/ requirements/

RUN pip install --no-cache-dir -r requirements/base.txt

# Copia o restante do código
COPY . .

# Expõe a porta se necessário (não obrigatório se só usar comandos internos)
EXPOSE 8002

ENV DJANGO_SETTINGS_MODULE=iot_simulator.settings

# Comando padrão (pode ser sobrescrito)
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
