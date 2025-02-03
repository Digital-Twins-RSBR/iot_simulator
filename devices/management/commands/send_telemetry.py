import time
import json
import random

from django.core.management.base import BaseCommand
from devices.models import Device
import paho.mqtt.client as mqtt

THINGSBOARD_HOST = "demo.thingsboard.io"
MQTT_PORT = 1883

class TelemetryPublisher:
    """
    Representa um dispositivo que se conecta via MQTT ao ThingsBoard, envia
    telemetria periodicamente e processa as chamadas RPC.
    """
    def __init__(self, device):
        self.device_pk = device.pk  # Armazena a PK para recarregar o device
        self.token = device.token
        self.client = mqtt.Client(client_id=self.token)
        self.client.username_pw_set(self.token)
        # Registra callbacks para conexão e mensagens (RPC)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect(THINGSBOARD_HOST, MQTT_PORT, 60)
        self.client.loop_start()  # Inicia o loop MQTT em background
    
    def on_connect(self, client, userdata, flags, rc):
        print(f"Device {self.token}: Conectado com o código {rc}")
        # Inscreve-se para receber chamadas RPC
        client.subscribe("v1/devices/me/rpc/request/+")
    
    def on_message(self, client, userdata, msg):
        print(f"Device {self.token}: Mensagem recebida no tópico {msg.topic}: {msg.payload.decode()}")
        try:
            payload = json.loads(msg.payload.decode())
            method = payload.get("method")
            params = payload.get("params")
            
            # Recarrega o device do banco para obter o estado atualizado
            device = Device.objects.get(pk=self.device_pk)
            device.refresh_from_db()
            device_type = device.device_type.name.lower()
            if device_type == "lightbulb":
                if method == "switchLed":
                    # Atualiza o estado do LED conforme o comando RPC recebido
                    new_status = bool(params)
                    device.state = {"status": new_status}
                    device.save()
                    telemetry = json.dumps({"status": new_status})
                    client.publish("v1/devices/me/telemetry", telemetry)
                    print(f"Device {device.device_id}: LED atualizado para {new_status} via RPC")
                elif method == "checkStatus":
                    telemetry = json.dumps(device.state)
                    response_topic = msg.topic.replace("request", "response")
                    client.publish(response_topic, telemetry)
                    print(f"Device {device.device_id}: Enviado checkStatus via RPC")
            elif device_type == "temperature sensor":
                if method == "checkStatus":
                    # Simula variação dos valores do sensor
                    current_state = device.state or {}
                    temperature = current_state.get("temperature", 25.0)
                    humidity = current_state.get("humidity", 50.0)
                    temperature += random.uniform(-0.5, 0.5)
                    humidity += random.uniform(-1, 1)
                    temperature = max(0, temperature)
                    humidity = max(0, min(100, humidity))
                    new_state = {"temperature": temperature, "humidity": humidity}
                    device.state = new_state
                    device.save()
                    telemetry = json.dumps(new_state)
                    response_topic = msg.topic.replace("request", "response")
                    client.publish(response_topic, telemetry)
                    print(f"Device {device.device_id}: Enviado DHT22 checkStatus via RPC")
            else:
                print(f"Device {device.device_id}: Tipo de dispositivo não suportado para RPC.")
        except Exception as e:
            print(f"Device {self.token}: Erro ao processar mensagem RPC: {e}")
    
    def publish(self, payload):
        self.client.publish("v1/devices/me/telemetry", payload)
    
    def send_telemetry(self):
        # Recarrega o device atualizado do banco
        device = Device.objects.get(pk=self.device_pk)
        device.refresh_from_db()
        device_type = device.device_type.name.lower()
        
        if device_type == "led":
            # Para LED, publica o estado salvo sem simulação
            # (assim, se via Admin ou RPC o estado foi alterado, esse valor será mantido)
            telemetry = json.dumps({"status": device.state.get("status", False)})
        elif device_type == "dht22":
            # Para DHT22, simula pequenas variações nos valores
            current_state = device.state or {}
            temperature = current_state.get("temperature", 25.0)
            humidity = current_state.get("humidity", 50.0)
            temperature += random.uniform(-0.5, 0.5)
            humidity += random.uniform(-1, 1)
            temperature = max(0, temperature)
            humidity = max(0, min(100, humidity))
            new_state = {"temperature": temperature, "humidity": humidity}
            device.state = new_state
            device.save()
            telemetry = json.dumps(new_state)
        else:
            telemetry = json.dumps(device.state)
        
        self.publish(telemetry)
        print(f"Device {device.device_id}: Telemetria enviada: {telemetry}")

class Command(BaseCommand):
    help = "Envia telemetria e processa chamadas RPC do ThingsBoard a cada 5 segundos para os dispositivos cadastrados."

    def handle(self, *args, **options):
        all_devices = Device.objects.all()
        if not all_devices:
            self.stdout.write("Nenhum dispositivo cadastrado.")
            return
        
        # Cria um TelemetryPublisher para cada dispositivo
        publishers = {}
        for device in all_devices:
            publishers[device.device_id] = TelemetryPublisher(device)
        
        self.stdout.write("Iniciando envio de telemetria (a cada 5 segundos) e aguardando RPCs...")
        try:
            while True:
                for device_id, publisher in publishers.items():
                    publisher.send_telemetry()
                time.sleep(5)
        except KeyboardInterrupt:
            self.stdout.write("Encerrando envio de telemetria e processamento de RPCs.")
