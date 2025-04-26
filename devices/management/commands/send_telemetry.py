import time
import json
import random

from django.conf import settings
from django.core.management.base import BaseCommand
import requests
from devices.models import Device
import paho.mqtt.client as mqtt

THINGSBOARD_HOST = "demo.thingsboard.io"
MQTT_PORT = 1883
# INFLUX configuration
INFLUXDB_HOST = settings.INFLUXDB_HOST
INFLUXDB_PORT = settings.INFLUXDB_PORT
INFLUXDB_BUCKET = settings.INFLUXDB_BUCKET
INFLUXDB_ORGANIZATION = settings.INFLUXDB_ORGANIZATION
INFLUXDB_URL = f"http://{INFLUXDB_HOST}:{INFLUXDB_PORT}/api/v2/write?org={INFLUXDB_ORGANIZATION}&bucket={INFLUXDB_BUCKET}&precision=ms"
INFLUXDB_TOKEN = settings.INFLUXDB_TOKEN

class TelemetryPublisher:
    """
    Represents a device that connects via MQTT to ThingsBoard, sends
    telemetry periodically, and processes RPC calls.
    """
    LIGHTS = ["led", "lightbulb"]
    TEMPERATURE_SENSOR = ["temperature sensor"]
    SOILHUMIDITY_SENSOR = ["soilhumidity sensor"]
    GAS_SENSOR = ["gas sensor"]
    AIR_CONDITIONER = ["airconditioner"]
    PUMP = ["pump"]
    POOL = ["pool"]
    GARDEN = ["garden"]
    IRRIGATION = ["irrigation"]

    def __init__(self, device, randomize=False):
        self.device_pk = device.pk  # Stores the PK to reload the device
        self.token = device.token
        self.randomize = randomize
        self.client = mqtt.Client(client_id=self.token)
        self.client.username_pw_set(self.token)
        # Registers callbacks for connection and messages (RPC)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect(THINGSBOARD_HOST, MQTT_PORT, 60)
        self.client.loop_start()  # Starts the MQTT loop in the background
    
    def on_connect(self, client, userdata, flags, rc):
        print(f"Device {self.token}: Connected with code {rc}")
        # Subscribes to receive RPC calls
        client.subscribe("v1/devices/me/rpc/request/+")
    
    def on_message(self, client, userdata, msg):
        print(f"Device {self.token}: Message received on topic {msg.topic}: {msg.payload.decode()}")
        try:
            payload = json.loads(msg.payload.decode())
            method = payload.get("method")
            params = payload.get("params")

            # Reloads the device from the database to get the updated state
            device = Device.objects.get(pk=self.device_pk)
            device.refresh_from_db()
            device_type = device.device_type.name.lower()
            
            # Registro do horário da modificação
            received_timestamp = int(time.time() * 1000)  # Timestamp em milissegundos
            
            headers = {
                "Authorization": f"Token {INFLUXDB_TOKEN}",
                "Content-Type": "text/plain"
            }
            
            if device_type in self.LIGHTS:
                if method == "switchLed":
                    # Atualiza o estado do LED com o comando recebido via RPC
                    new_status = bool(params)
                    device.state = {"status": new_status}
                    device.save()

                    telemetry = json.dumps({"status": new_status})
                    client.publish("v1/devices/me/telemetry", telemetry)
                    print(f"Device {device.device_id}: LED updated to {new_status} via RPC")
                    
                    # Envia os dados para o InfluxDB registrando o evento
                    data = f"device_data,sensor={device.device_id},source=simulator status={int(new_status)},received_timestamp={received_timestamp} {received_timestamp}"
                    response = requests.post(INFLUXDB_URL, headers=headers, data=data)
                    print(f"Response Code: {response.status_code}, Response Text: {response.text}")

                    # Envia a resposta para o ThingsBoard
                    response_topic = msg.topic.replace("request", "response")
                    client.publish(response_topic, json.dumps({"status": new_status}))

                if method == "checkStatus":
                    telemetry = device.state.get("status", False)
                    response_topic = msg.topic.replace("request", "response")
                    client.publish(response_topic, json.dumps({"status": telemetry}))

            elif device_type in self.TEMPERATURE_SENSOR + self.AIR_CONDITIONER:
                if method == "checkStatus":
                    # Simula variação nos valores do sensor
                    current_state = device.state or {}
                    temperature = current_state.get("temperature", 25.0)
                    humidity = current_state.get("humidity", 50.0)
                    temperature += random.uniform(-0.5, 0.5)
                    humidity += random.uniform(-1, 1)
                    temperature = max(0, temperature)
                    humidity = max(0, min(100, humidity))
                    new_state = {"temperature": temperature, "humidity": humidity, "status": current_state.get("status", False)}
                    device.state = new_state
                    device.save()

                    telemetry = json.dumps(new_state)
                    response_topic = msg.topic.replace("request", "response")
                    client.publish(response_topic, telemetry)
                    print(f"Device {device.device_id}: Sent DHT22 checkStatus via RPC")

                    # Envia os dados para o InfluxDB registrando o evento
                    data = f"device_data,sensor={device.device_id},source=simulator temperature={temperature},humidity={humidity},received_timestamp={received_timestamp} {received_timestamp}"
                    response = requests.post(INFLUXDB_URL, headers=headers, data=data)
                    print(f"Response Code: {response.status_code}, Response Text: {response.text}")
                    
            else:
                print(f"Device {device.device_id}: Unsupported device type for RPC.")
        except Exception as e:
            print(f"Device {self.token}: Error processing RPC message: {e}")

    
    def publish(self, payload):
        self.client.publish("v1/devices/me/telemetry", payload)
    
    def send_telemetry(self):
        # Reloads the updated device from the database
        device = Device.objects.get(pk=self.device_pk)
        device.refresh_from_db()
        device_type = device.device_type.name.lower()
        
        if self.randomize:
            if device_type in self.LIGHTS:
                # Randomize boolean value for LED status
                new_status = bool(random.getrandbits(1))
                device.state = {"status": new_status}
                telemetry = json.dumps({"status": new_status})
            elif device_type in self.AIR_CONDITIONER + self.TEMPERATURE_SENSOR:
                # Randomize temperature and humidity values
                temperature = round(random.uniform(16, 28), 2)
                humidity = round(random.uniform(50, 80), 2)
                status = bool(random.getrandbits(1))
                device.state = {"temperature": temperature, "humidity": humidity, "status": status}
                telemetry = json.dumps({"temperature": temperature, "humidity": humidity, "status": status})
            else:
                telemetry = json.dumps(device.state)
            device.save()
        else:
            if device_type in self.LIGHTS:
                telemetry = json.dumps({"status": device.state.get("status", False)})
            else:
                telemetry = json.dumps(device.state)
        
        self.publish(telemetry)
        print(f"Device {device.device_id}: Telemetry sent: {telemetry}")

class Command(BaseCommand):
    help = "Sends telemetry and processes RPC calls from ThingsBoard every 5 seconds for registered devices."

    def add_arguments(self, parser):
        parser.add_argument(
            '--use-influxdb',
            action='store_true',
            help='Use InfluxDB for storing telemetry data'
        )
        parser.add_argument(
            '--randomize',
            action='store_true',
            help='Randomize device properties'
        )
        parser.add_argument(
            '--device-id',
            nargs='+',
            type=str,
            help='Specify one or more device IDs to send telemetry data'
        )

    def handle(self, *args, **options):
        use_influxdb = options['use_influxdb']
        randomize = options['randomize']
        device_ids = options['device_id']
        
        if device_ids:
            all_devices = Device.objects.filter(id__in=device_ids)
        else:
            all_devices = Device.objects.all()
        
        if not all_devices:
            self.stdout.write("No devices registered.")
            return
        
        # Creates a TelemetryPublisher for each device
        publishers = {}
        for device in all_devices:
            publishers[device.device_id] = TelemetryPublisher(device, randomize=randomize)
        
        self.stdout.write("Starting telemetry sending (every 5 seconds) and waiting for RPCs...")
        try:
            while True:
                for device_token, publisher in publishers.items():
                    if use_influxdb:
                        headers = {
                            "Authorization": f"Token {INFLUXDB_TOKEN}",
                            "Content-Type": "text/plain",
                        }
                        device = Device.objects.filter(device_id=device_token).first()
                        if device:
                            sensor_name_lower = device.device_type.name.lower()
                            if sensor_name_lower in ["temperature sensor", "dht22", "airconditioner"]:
                                temperature = round(random.uniform(20, 30), 2)
                                humidity = round(random.uniform(40, 60), 2)
                                device.state = {"temperature": temperature, "humidity": humidity}
                                device.save()
                                timestamp = int(time.time() * 1000)  # Timestamp in ms
                                data = f"device_data,sensor={device.device_id},source=simulator temperature={temperature},humidity={humidity},sent_timestamp={timestamp} {timestamp}"
                                response = requests.post(INFLUXDB_URL, headers=headers, data=data)
                                print(f"Response Code: {response.status_code}, Response Text: {response.text}")
                                if response.status_code != 204:
                                    print(f"Error sending data to InfluxDB: {response.status_code} - {response.text}")
                                    continue  # Skip sending telemetry if InfluxDB registration fails
                            elif sensor_name_lower in ["led", "lightbulb"]:
                                status = device.state.get("status", False)
                                device.state = {"status": status}
                                device.save()
                                timestamp = int(time.time() * 1000) # Timestamp in ms
                                data = f"device_data,sensor={device.device_id},source=simulator status={int(status)},sent_timestamp={timestamp} {timestamp}"
                                response = requests.post(INFLUXDB_URL, headers=headers, data=data)
                                print(f"Response Code: {response.status_code}, Response Text: {response.text}")
                                if response.status_code != 204:
                                    print(f"Error sending data to InfluxDB: {response.status_code} - {response.text}")
                                    continue  # Skip sending telemetry if InfluxDB registration fails
                            else:
                                # Handle other device types if necessary
                                pass

                    publisher.send_telemetry()
                time.sleep(5)
        except KeyboardInterrupt:
            self.stdout.write("Stopping telemetry sending and RPC processing.")
