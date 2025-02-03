import time
import json
import random

from django.core.management.base import BaseCommand
from devices.models import Device
import paho.mqtt.client as mqtt

# Configurações para conexão com o ThingsBoard
THINGSBOARD_HOST = "demo.thingsboard.io"
MQTT_PORT = 1883

class TelemetryPublisher:
    """
    Classe auxiliar para conectar via MQTT e publicar telemetria para um dispositivo.
    """
    def __init__(self, device):
        self.device_pk = device.pk  # armazena a chave primária para recarregar o device sempre que necessário
        self.token = device.token
        self.client = mqtt.Client(client_id=self.token)
        self.client.username_pw_set(self.token)
        self.client.connect(THINGSBOARD_HOST, MQTT_PORT, 60)
        # Inicia o loop MQTT em background
        self.client.loop_start()
    
    def publish(self, payload):
        # Publica no tópico padrão de telemetria do ThingsBoard
        self.client.publish("v1/devices/me/telemetry", payload)
    
    def send_telemetry(self):
        # Recarrega o device atualizado do banco de dados
        device = Device.objects.get(pk=self.device_pk)
        device_type = device.device_type.name.lower()
        
        if device_type == "led":
            # Para dispositivos LED, envia o status salvo
            telemetry = json.dumps({"status": device.state.get("status", False)})
        elif device_type == "dht22":
            # Para sensores DHT22, simula variações nos valores
            current_state = device.state
            temperature = current_state.get("temperature", 25.0)
            humidity = current_state.get("humidity", 50.0)
            temperature += random.uniform(-0.5, 0.5)
            humidity += random.uniform(-1, 1)
            temperature = max(0, temperature)
            humidity = max(0, min(100, humidity))
            new_state = {"temperature": temperature, "humidity": humidity}
            # Atualiza o estado do device no banco de dados
            device.state = new_state
            device.save()
            telemetry = json.dumps(new_state)
        else:
            telemetry = json.dumps(device.state)
        
        self.publish(telemetry)
        print(f"Device {device.device_id}: Telemetria enviada: {telemetry}")

class Command(BaseCommand):
    help = "Envia periodicamente telemetria para os dispositivos registrados para o ThingsBoard"

    def handle(self, *args, **options):
        # Carrega todos os dispositivos cadastrados
        all_devices = Device.objects.all()
        if not all_devices:
            self.stdout.write("Nenhum dispositivo cadastrado.")
            return

        # Cria um publicador para cada dispositivo
        publishers = {}
        for device in all_devices:
            publishers[device.device_id] = TelemetryPublisher(device)
        
        self.stdout.write("Iniciando envio de telemetria para os dispositivos (a cada 5 segundos)...")
        try:
            while True:
                for device_id, publisher in publishers.items():
                    publisher.send_telemetry()
                # Intervalo de 5 segundos entre os envios
                time.sleep(5)
        except KeyboardInterrupt:
            self.stdout.write("Encerrando envio de telemetria.")
