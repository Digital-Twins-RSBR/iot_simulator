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
    Represents a device that connects via MQTT to ThingsBoard, sends
    telemetry periodically, and processes RPC calls.
    """
    def __init__(self, device):
        self.device_pk = device.pk  # Stores the PK to reload the device
        self.token = device.token
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
            if device_type == "lightbulb":
                if method == "switchLed":
                    # Updates the LED state according to the received RPC command
                    new_status = bool(params)
                    device.state = {"status": new_status}
                    device.save()
                    telemetry = json.dumps({"status": new_status})
                    client.publish("v1/devices/me/telemetry", telemetry)
                    print(f"Device {device.device_id}: LED updated to {new_status} via RPC")
                elif method == "checkStatus":
                    telemetry = json.dumps(device.state)
                    response_topic = msg.topic.replace("request", "response")
                    client.publish(response_topic, telemetry)
                    print(f"Device {device.device_id}: Sent checkStatus via RPC")
            elif device_type == "temperature sensor":
                if method == "checkStatus":
                    # Simulates variation in sensor values
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
                    print(f"Device {device.device_id}: Sent DHT22 checkStatus via RPC")
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
        
        if device_type == "led":
            # For LED, publishes the saved state without simulation
            # (thus, if the state was changed via Admin or RPC, this value will be maintained)
            telemetry = json.dumps({"status": device.state.get("status", False)})
        elif device_type == "dht22":
            # For DHT22, simulates small variations in values
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
        print(f"Device {device.device_id}: Telemetry sent: {telemetry}")

class Command(BaseCommand):
    help = "Sends telemetry and processes RPC calls from ThingsBoard every 5 seconds for registered devices."

    def handle(self, *args, **options):
        all_devices = Device.objects.all()
        if not all_devices:
            self.stdout.write("No devices registered.")
            return
        
        # Creates a TelemetryPublisher for each device
        publishers = {}
        for device in all_devices:
            publishers[device.device_id] = TelemetryPublisher(device)
        
        self.stdout.write("Starting telemetry sending (every 5 seconds) and waiting for RPCs...")
        try:
            while True:
                for device_id, publisher in publishers.items():
                    publisher.send_telemetry()
                time.sleep(5)
        except KeyboardInterrupt:
            self.stdout.write("Stopping telemetry sending and RPC processing.")
