# IOT Simulator

O **IOT Simulator** é uma ferramenta desenvolvida em Django para simular dispositivos IoT que se comunicam com o ThingsBoard. Com ela, é possível cadastrar dispositivos (por meio do Django Admin) e, a partir disso, enviar periodicamente dados de telemetria para o ThingsBoard via MQTT – simulando o comportamento de dispositivos físicos (como LEDs e sensores DHT22). A ferramenta também oferece uma interface para processar chamadas RPC (Remote Procedure Call) e atualizar o estado dos dispositivos, facilitando a integração com soluções de digital twin e middleware de IoT.

## Componentes do Projeto

### 1. Modelos (Models)
- **DeviceType**: Define o tipo de dispositivo (por exemplo, "led" ou "dht22"). Cada tipo pode ter uma implementação padrão de métodos RPC.
- **Device**: Representa um dispositivo IoT, armazenando o `device_id`, `token` (para autenticação com o ThingsBoard) e o estado atual (armazenado em um campo JSON).

### 2. RPC Handlers
Cada tipo de dispositivo possui um _handler_ responsável por implementar os métodos RPC padrão:
- **LEDHandler**: Implementa os métodos `"switchLed"` (para ligar/desligar o LED) e `"checkStatus"` (para retornar o status atual).
- **DHT22Handler**: Implementa o método `"checkStatus"`, que simula leituras de temperatura e umidade, atualizando os valores com variações aleatórias.

Um registro (_registry_) (`RPC_HANDLER_REGISTRY`) mapeia o nome do tipo de dispositivo para o handler correspondente.

### 3. Endpoints e Comunicação com o ThingsBoard
- **Endpoint RPC**: Exposto em `/devices/rpc/<device_id>/` via método POST. Esse endpoint recebe um payload JSON com o método RPC e os parâmetros, repassa a chamada para o handler correspondente e retorna a resposta.
- **Management Command para Telemetria**: Um comando Django (`send_telemetry`) que, a partir dos dispositivos cadastrados, envia periodicamente (a cada 10 segundos) os dados de telemetria para o ThingsBoard utilizando o protocolo MQTT. Essa funcionalidade simula o `loop()` de um dispositivo físico.

### 4. Integração com o Django Admin
Utilize a interface administrativa do Django para:
- Cadastrar os **DeviceTypes** (por exemplo, "led" e "dht22").
- Cadastrar os **Devices** associando cada dispositivo ao seu tipo, definindo o `device_id`, `token` e o estado inicial.

## Como Usar o IOT Simulator

### Pré-requisitos
- Python 3.7+ (recomendado)
- Django (3.1 ou superior)
- paho-mqtt

### Instalação e Configuração
1. **Clone o Repositório e Crie o Ambiente Virtual:**
   ```bash
   git clone <URL_DO_REPOSITÓRIO>
   cd iot-simulator
   python -m venv venv
   source venv/bin/activate  # ou venv\Scripts\activate no Windows
   ```
2. **Instale as Dependências**:
    ```bash
    pip install -Ur requirements/base.txt
    ```
3. Configure o Projeto Django
    - Realize as configurações de banco de dados e demais ajustes no arquivo myproject/settings.py conforme sua necessidade
    - Execute as migrações:
    ```bash
    python manage.py migrate
    ```
4. Crie um Superusuário para Acessar o Admin:
    ```bash
    python manage.py createsuperuser
    ```

### Usando o IOT Simulator

#### Cadastro de Dispositivos
1. Acesse o Django Admin:
    -  Inicie o servidor:
    ```bash
    python manage.py runserver
    ```
    - Acesse http://localhost:<porta>/admin/ e faça login com o superusuário criado.
2. Cadastre os Tipos de dispositivo
    - Crie entradas em DeviceType(ex: led e dht22)
3. Cadastre os Dispositivos
    - Em Device, cadastre cada dispositivo informando:
        - device_id: Identificador único do dispositivo.
        - device_type: Selecione o tipo correspondente.
        - token: Token utilizado para autenticação com o ThingsBoard.
        - state: Estado inicial (ex.: {"status": false} para um LED ou {"temperature": 25.0, "humidity": 50.0} para um sensor).

### Configuração no ThingsBoard
1. Acesse o ThingsBoard:
    - Utilize o demo.thingsboard.io ou sua instância local.
2. Cadastro dos Dispositivos no ThingsBoard:
    - Crie um dispositivo no ThingsBoard para cada dispositivo cadastrado no Django.
    - Configure o token do dispositivo no ThingsBoard exatamente como cadastrado no Django.
    - Certifique-se de que o dispositivo no ThingsBoard esteja configurado para receber telemetria no tópico padrão v1/devices/me/telemetry e chamadas RPC nos tópicos de request/resposta.

### Executando a Simulação de Telemetria
1. Inicie o Comando de Telemetria:
    - Em um terminal, execute:
    ```bash
    python manage.py send_telemetry
    ```
    - Este comando conectará cada dispositivo ao ThingsBoard via MQTT e enviará os dados de telemetria periodicamente (a cada 10 segundos), simulando o funcionamento contínuo dos dispositivos.
2. Verifique os Dados no ThingsBoard:
    - No dashboard do ThingsBoard, visualize os dados de telemetria e as chamadas RPC para confirmar que os dispositivos simulados estão se comunicando corretamente.

### Extensibilidade
    - Novos Tipos de Dispositivos:
    Para adicionar novos tipos, crie um novo handler em devices/rpc_handlers.py implementando os métodos RPC desejados e adicione-o ao RPC_HANDLER_REGISTRY.
    - Endpoints Adicionais:
    É possível estender a API com novos endpoints para, por exemplo, receber comandos adicionais, configurar intervalos de telemetria ou integrar outras funcionalidades.


### Como funciona o processo telemetria e sincronização das propriedades:

#### Conexão e Subscrição para RPC:
- Cada instância de TelemetryPublisher cria um cliente MQTT usando o token do dispositivo e registra os callbacks on_connect e on_message.
    No on_connect, o cliente se inscreve no tópico v1/devices/me/rpc/request/+ para receber as chamadas RPC enviadas pelo ThingsBoard.
    O on_message processa a mensagem recebida, diferenciando o comportamento para dispositivos do tipo led (por exemplo, processando o método "switchLed" ou "checkStatus") e dht22 (processando "checkStatus").

#### Envio de Telemetria:
    - O método send_telemetry() recarrega o dispositivo do banco de dados (para refletir alterações feitas via Django Admin), simula eventuais variações (no caso do sensor DHT22) e envia o payload via MQTT.

    - Loop de Sincronização a Cada 5 Segundos:
    No comando, o loop principal percorre todos os dispositivos e chama send_telemetry() a cada 5 segundos. Assim, além de enviar os dados de telemetria, o dispositivo permanece “escutando” as mensagens RPC e respondendo-as conforme necessário.

Ao executar o comando:
    ´´´bash
    python manage.py send_telemetry
    ´´´
cada dispositivo será conectado ao ThingsBoard, enviará telemetria periodicamente e ficará aguardando (e processando) chamadas RPC que possam alterar seu estado ou solicitar informações.
Essa abordagem garante que tanto as atualizações feitas via Admin quanto as chamadas do ThingsBoard sejam refletidas e sincronizadas em tempo real.
