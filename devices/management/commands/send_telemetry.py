import time
import json
import random
import asyncio
import aiohttp
import aiomqtt
from asgiref.sync import sync_to_async
from collections import defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand
from devices.models import Device
import re


THINGSBOARD_HOST = settings.THINGSBOARD_HOST
if THINGSBOARD_HOST.startswith("http://"):
    THINGSBOARD_HOST = THINGSBOARD_HOST[len("http://"):]
elif THINGSBOARD_HOST.startswith("https://"):
    THINGSBOARD_HOST = THINGSBOARD_HOST[len("https://"):]
# Remove porta se existir (ex: localhost:1883 -> localhost)
THINGSBOARD_HOST = re.split(r':', THINGSBOARD_HOST)[0]


THINGSBOARD_API_URL = f"https://{THINGSBOARD_HOST}/api"
THINGSBOARD_MQTT_PORT = settings.THINGSBOARD_MQTT_PORT
THINGSBOARD_MQTT_KEEP_ALIVE = settings.THINGSBOARD_MQTT_KEEP_ALIVE
HEARTBEAT_INTERVAL = settings.HEARTBEAT_INTERVAL

# INFLUX configuration
INFLUXDB_HOST = settings.INFLUXDB_HOST
INFLUXDB_PORT = settings.INFLUXDB_PORT
INFLUXDB_BUCKET = settings.INFLUXDB_BUCKET
INFLUXDB_ORGANIZATION = settings.INFLUXDB_ORGANIZATION
INFLUXDB_URL = f"http://{INFLUXDB_HOST}:{INFLUXDB_PORT}/api/v2/write?org={INFLUXDB_ORGANIZATION}&bucket={INFLUXDB_BUCKET}&precision=ms"
INFLUXDB_TOKEN = settings.INFLUXDB_TOKEN


async def post_to_influx(session, data, device=None):
    """Helper to POST line-protocol to Influx and print detailed debug info about the device and payload."""
    headers = {
        "Authorization": f"Token {INFLUXDB_TOKEN}",
        "Content-Type": "text/plain",
    }
    # Debug print of device fields (safe access)
    try:
        if device is not None:
            try:
                dev_info = {
                    'device_id': getattr(device, 'device_id', None),
                    'token': (getattr(device, 'token', None)[:12] + '...') if getattr(device, 'token', None) else None,
                    'thingsboard_id': getattr(device, 'thingsboard_id', None),
                    'state': getattr(device, 'state', None),
                }
            except Exception:
                dev_info = str(device)
        else:
            dev_info = '<no device object>'
    except Exception:
        dev_info = '<error reading device>'

    print('--- InfluxDB write debug ---')
    print('Device:', dev_info)
    # also print raw token and derived sensor_tag for diagnosis
    try:
        raw_t = None
        if device is not None:
            raw_t = getattr(device, 'token', None)
        print('Raw token:', raw_t)
        if raw_t:
            sensor_tag_dbg = str(raw_t).replace('\\', '\\\\').replace(',', '\\,').replace(' ', '\\ ').replace('=', '\\=')
        else:
            sensor_tag_dbg = None
        print('Derived sensor_tag (escaped):', sensor_tag_dbg)
    except Exception:
        pass
    print('Line protocol to send:')
    print(data)

    try:
        async with session.post(INFLUXDB_URL, headers=headers, data=data) as response:
            text = await response.text()
            print(f"Response Code: {response.status}, Response Text: {text}")
            return response.status, text
    except Exception as e:
        print('Exception while sending to InfluxDB:', e)
        import traceback
        traceback.print_exc()
        raise


DEVICE_STATE = defaultdict(dict)


class InMemoryDeviceProxy:
    """A tiny proxy used when the simulator runs with --memory.
    It exposes .state and a sync .save() that updates the global DEVICE_STATE
    so existing code that calls device.state and sync_to_async(device.save)()
    continues to work without hitting AttributeError on None.
    """
    def __init__(self, device_id):
        self.device_id = device_id
        # Ensure a dict exists for this device
        if device_id not in DEVICE_STATE:
            DEVICE_STATE[device_id] = {}
        # keep a reference so updates are reflected in DEVICE_STATE
        self.state = DEVICE_STATE[device_id]

    def save(self):
        # Persist current state back to the global dict (no-op if same object)
        DEVICE_STATE[self.device_id] = self.state

class TelemetryPublisher:
    """
    Represents a device that connects via MQTT to ThingsBoard, sends
    telemetry periodically, and processes RPC calls.
    """
    LIGHTS = ["led", "lightbulb"]
    TEMPERATURE_SENSOR = ["temperature sensor"]
    SOILHUMIDITY_SENSOR = ["soilhumidity sensor", "soil humidity sensor"]
    GAS_SENSOR = ["gas sensor"]
    AIR_CONDITIONER = ["airconditioner"]
    PUMP = ["pump"]
    POOL = ["pool"]
    GARDEN = ["garden"]
    IRRIGATION = ["irrigation"]

    def __init__(self, device, randomize=False, session=None, use_memory=False, device_type_name=""):
        self.device_pk = device.pk
        self.token = device.token
        self.device_id = device.device_id
        # use thingsboard_id as canonical identifier for external systems (eg. Influx)
        self.thingsboard_id = getattr(device, 'thingsboard_id', None)
        self._device_type_name = device_type_name  # sempre passado já resolvido
        self.randomize = randomize
        self.client_id = self.token
        self.mqtt_client = None
        self.session = session
        self.use_memory = use_memory

    @classmethod
    async def create(cls, device, randomize=False, session=None, use_memory=False, device_type_name=""):
        # Sempre tenta garantir token válido
        await sync_to_async(device.save)()
        token = device.token
        if not token:
            print(f"[telemetry][ERRO] Device {device.device_id} continua sem token após save(). Não será possível conectar ao ThingsBoard.")
        else:
            print(f"[telemetry] Device {device.device_id} pronto para conectar com token {token[:8]}... (ocultado)" )
        return cls(device, randomize=randomize, session=session, use_memory=use_memory, device_type_name=device_type_name)

    @property
    def device_type(self):
        return self._device_type_name

    async def connect(self, spawn_handle: bool = True):
        # Antes de tentar conectar, tente uma reconciliação rápida no banco para
        # garantir token/credentials atualizados (poderá retornar precocemente se
        # ThingsBoard estiver inacessível; nesse caso o loop de conexão continuará).
        try:
            device = await sync_to_async(Device.objects.get)(pk=self.device_pk)
            # chama save() para forçar a lógica de sincronização com ThingsBoard
            await sync_to_async(device.save)()
            await sync_to_async(device.refresh_from_db)()
            if device.token:
                self.token = device.token
                self.client_id = device.token
        except Exception as e:
            # falhas aqui são esperadas se ThingsBoard estiver indisponível; o loop abaixo fará retries
            print(f"[telemetry] Reconciliação pré-conexão falhou (ignorado por agora): {e}")

        # Crie o client DENTRO do contexto async, pois aiomqtt precisa de um event loop rodando
        self.mqtt_client = aiomqtt.Client(
            hostname=THINGSBOARD_HOST,
            port=THINGSBOARD_MQTT_PORT,
            username=self.token,
            password=None,
            keepalive=THINGSBOARD_MQTT_KEEP_ALIVE
        )
        # Tentar conectar com retries exponenciais para tolerar brokers que ainda
        # não aceitaram conexões no momento inicial.
        # Persistent connect: keep retrying until ThingsBoard accepts the TCP/MQTT connection
        delay = 1
        timeout_per_attempt = 10  # Keep default timeout to avoid premature failures
        attempt = 0
        while True:
            attempt += 1
            try:
                self._mqtt_context = self.mqtt_client.__aenter__()
                await asyncio.wait_for(self._mqtt_context, timeout=timeout_per_attempt)
                # Se conectou, subscribe e continue
                print(f"[MQTT CONNECT] Device {self.token} connected to MQTT broker")
                await self.mqtt_client.subscribe("v1/devices/me/rpc/request/+")
                print(f"[MQTT SUBSCRIBE] Device {self.token} subscribed to RPC topic: v1/devices/me/rpc/request/+")
                # Only spawn a handle_rpc task if requested and not already running
                try:
                    if spawn_handle:
                        if not hasattr(self, '_rpc_task') or self._rpc_task.done():
                            self._rpc_task = asyncio.create_task(self.handle_rpc())
                            print(f"[MQTT HANDLER] Device {self.token} started RPC handler task")
                except Exception as e:
                    print(f"[MQTT HANDLER ERROR] Device {self.token}: {e}")
                    # If task creation fails, continue; handle_rpc will be invoked on next successful connect
                    pass
                print(f"[mqtt] Device {self.token} connected to {THINGSBOARD_HOST}:{THINGSBOARD_MQTT_PORT} on attempt {attempt}")
                return True
            except asyncio.TimeoutError:
                print(f"[mqtt] connect attempt {attempt} timed out after {timeout_per_attempt}s; retrying in {delay}s")
            except Exception as e:
                # detect MQTT auth failure (ThingsBoard token invalid)
                msg = str(e)
                if 'Not authorized' in msg or 'code:135' in msg or 'Not authorized' in getattr(e, 'args', [''])[0]:
                    print(f"[mqtt] connect attempt {attempt} failed: AUTH error ({e}); attempting token reconciliation...")
                    try:
                        # fetch fresh device from DB and trigger save() to refresh token / thingsboard mapping
                        device = await sync_to_async(Device.objects.get)(pk=self.device_pk)
                        # call save() in threadpool so Device.save() can perform network calls
                        await sync_to_async(device.save)()
                        # reload token after reconciliation
                        await sync_to_async(device.refresh_from_db)()
                        new_token = device.token
                        if new_token:
                            self.token = new_token
                            self.client_id = new_token
                            print(f"[mqtt] reconciliation updated token for {self.device_id[:40]}...; retrying connect")
                        else:
                            print(f"[mqtt] reconciliation did not produce a token for {self.device_id}; will retry later")
                    except Exception as re:
                        print(f"[mqtt] reconciliation attempt failed: {re}; will retry connect loop")
                else:
                    print(f"[mqtt] connect attempt {attempt} failed: {type(e).__name__}: {e}; retrying in {delay}s")
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)

    async def handle_rpc(self):
        # Para aiomqtt >= 1.0.0, 'messages' é um async iterator, não um context manager.
        while True:
            try:
                async for msg in self.mqtt_client.messages:
                    await self.on_message(msg)
            except aiomqtt.MqttError as me:
                # Handle disconnects by attempting a reconnect without spawning another handle_rpc task
                print(f"[mqtt] message iterator error: {me}; attempting reconnect...")
                try:
                    await asyncio.sleep(0.5)
                    await self.connect(spawn_handle=False)
                except Exception as recon_e:
                    print(f"[mqtt] reconnect attempt failed: {recon_e}; will retry shortly")
                    await asyncio.sleep(1)
                # loop and resume listening
                continue
            except Exception as e:
                print(f"[mqtt] unexpected error in handle_rpc: {e}")
                await asyncio.sleep(1)
                continue

    async def on_message(self, msg):
        # Normalize topic to string (aiomqtt may provide a Topic object)
        topic_str = str(msg.topic)
        print(f"[MQTT RECEIVED] Device {self.token}: Message on topic {topic_str}: {msg.payload.decode()}")

        # Parse payload safely
        try:
            payload = json.loads(msg.payload.decode())
        except Exception as e:
            print(f"[MQTT ERROR] Failed to parse JSON: {e}")
            payload = {}
        method = payload.get("method")
        params = payload.get("params")

        # Extract request id from topic (ThingsBoard uses v1/devices/me/rpc/request/<id>)
        try:
            request_id = topic_str.split('/')[-1]
        except Exception:
            request_id = None

        device_id = self.device_id
        try:
            received_timestamp = int(time.time() * 1000)
            print(f"[M2S RPC RECEIVED] device={device_id}, method={method}, timestamp={received_timestamp}, request_id={request_id}")

            # Write M2S received_timestamp to InfluxDB for ODTE latency measurement
            try:
                raw_token = getattr(self, 'thingsboard_id', None)
                print(f"[M2S INFLUX] raw_token={raw_token}, session={self.session is not None}")
                
                if raw_token and self.session:
                    sensor_tag = str(raw_token).replace('\\', '\\\\').replace(',', '\\,').replace(' ', '\\ ').replace('=', '\\=')
                    # Write M2S received_timestamp to latency_measurement using source=simulator
                    # Use only numeric fields to avoid InfluxDB type conflicts
                    influx_data = f"latency_measurement,sensor={sensor_tag},source=simulator received_timestamp={received_timestamp} {received_timestamp}"
                    await post_to_influx(self.session, influx_data, None)
                    print(f"[M2S] Simulator received RPC {method} at {received_timestamp} - written to InfluxDB")
                else:
                    print(f"[DEBUG M2S] Skipping InfluxDB write: raw_token={raw_token}, session={self.session is not None}")
            except Exception as e:
                print(f"[M2S] Failed to write received_timestamp to InfluxDB: {e}")
                import traceback
                traceback.print_exc()

            # Log RPC reception to deploy/logs/simulator_rpc_received.log for auditing
            try:
                import pathlib, getpass
                log_dir = pathlib.Path(__file__).resolve().parents[3] / 'deploy' / 'logs'
                log_dir.mkdir(parents=True, exist_ok=True)
                recv_log = log_dir / 'simulator_rpc_received.log'
                # Mask token for privacy (show first 6 chars)
                masked = (self.token[:6] + '...') if getattr(self, 'token', None) else None
                recv_entry = {
                    'ts': received_timestamp,
                    'device_id': device_id,
                    'thingsboard_id': getattr(self, 'thingsboard_id', None),
                    'masked_token': masked,
                    'request_id': request_id,
                    'method': method,
                    'params': params,
                    'topic': topic_str
                }
                with recv_log.open('a') as rf:
                    rf.write(json.dumps(recv_entry) + '\n')
            except Exception:
                # Swallow logging errors to avoid affecting RPC handling
                pass

            # Write M2S received_timestamp to InfluxDB for latency calculation
            try:
                raw_token = getattr(self, 'thingsboard_id', None)
                if raw_token and hasattr(self, 'session') and self.session:
                    sensor_tag = str(raw_token).replace('\\', '\\\\').replace(',', '\\,').replace(' ', '\\ ').replace('=', '\\=')
                    # Write to latency_measurement table with direction=M2S for matching with sent_timestamp
                    influx_data = f"latency_measurement,sensor={sensor_tag},direction=M2S received_timestamp={received_timestamp},request_id=\"{request_id}\",method=\"{method}\" {received_timestamp}"
                    await post_to_influx(self.session, influx_data, None)
                    print(f"[M2S] Recorded received_timestamp {received_timestamp} for {sensor_tag} method {method}")
            except Exception as e:
                # Swallow InfluxDB errors to avoid affecting RPC handling
                print(f"[M2S] Failed to write received_timestamp: {e}")
                import traceback
                traceback.print_exc()

            # Use armazenamento em memória ou banco conforme o modo
            # Initialize local device_type with fallback to self.device_type so it's always defined
            device_type = self.device_type
            if self.use_memory:
                # Use an in-memory proxy so existing code that expects a Device
                # object with .state and .save() continues to work.
                state = DEVICE_STATE[device_id]
                device = InMemoryDeviceProxy(device_id)
            else:
                device = await sync_to_async(Device.objects.get)(pk=self.device_pk)
                await sync_to_async(device.refresh_from_db)()
                state = device.state or {}
                # resolve device_type from device instance if possible
                try:
                    device_type = (device.device_type.name or "").lower()
                except Exception:
                    # keep the fallback already assigned from self.device_type
                    pass

            async def send_influx(data, device_obj=None):
                # helper: forward to shared post_to_influx, prefer explicit device_obj when provided
                try:
                    await post_to_influx(self.session, data, device_obj if device_obj is not None else device)
                except Exception:
                    # swallow to avoid breaking RPC handling
                    import traceback
                    traceback.print_exc()

            # For external storages like Influx, use the device token as canonical identifier
            raw_token = getattr(self, 'thingsboard_id', None)
            if raw_token:
                sensor_tag = str(raw_token).replace('\\', '\\\\').replace(',', '\\,').replace(' ', '\\ ').replace('=', '\\=')
            else:
                sensor_tag = None

            response_topic = topic_str.replace("request", "response")

            # Handle device-specific RPC methods
            if device_type in self.LIGHTS or device_type == "lightbulb":
                if method == "switchLed":
                    new_status = bool(params)
                    if self.use_memory:
                        DEVICE_STATE[device_id]['status'] = new_status
                    else:
                        device.state = {"status": new_status}
                        await sync_to_async(device.save)()
                    telemetry = json.dumps({"status": new_status})
                    await self.mqtt_client.publish("v1/devices/me/telemetry", telemetry)
                    print(f"Device {device_id}: LED updated to {new_status} via RPC")
                    data = f"device_data,sensor={sensor_tag},source=simulator status={float(1.0 if new_status else 0.0)},received_timestamp={received_timestamp} {received_timestamp}"
                    if sensor_tag:
                        await send_influx(data)
                    else:
                        print(f"Skipping Influx write: device {device_id} has no token")

                    # Reply to the RPC request so ThingsBoard doesn't report TIMEOUT for two-way RPCs
                    if request_id:
                        try:
                            resp_topic = f"v1/devices/me/rpc/response/{request_id}"
                            resp_payload = json.dumps({"status": new_status})
                            await self.publish_rpc_response(resp_topic, resp_payload)
                        except Exception as e:
                            print(f"Device {device_id}: Failed to publish RPC response: {e}")

                    await self.publish_rpc_response(response_topic, json.dumps({"status": new_status}))

                if method == "checkStatus":
                    status = DEVICE_STATE[device_id].get("status", False) if self.use_memory else (device.state.get("status", False) if device and device.state else False)
                    await self.publish_rpc_response(response_topic, json.dumps({"status": status}))

            elif device_type in self.TEMPERATURE_SENSOR or device_type == "temperature sensor":
                if method == "checkStatus":
                    if self.use_memory:
                        temperature = DEVICE_STATE[device_id].get("temperature", 25.0)
                        temperature += random.uniform(-0.5, 0.5)
                        temperature = max(0, temperature)
                        DEVICE_STATE[device_id] = {"temperature": temperature}
                        telemetry = json.dumps({"temperature": temperature})
                    else:
                        current_state = device.state or {}
                        temperature = current_state.get("temperature", 25.0)
                        temperature += random.uniform(-0.5, 0.5)
                        temperature = max(0, temperature)
                        new_state = {"temperature": temperature}
                        device.state = new_state
                        await sync_to_async(device.save)()
                        telemetry = json.dumps(new_state)

                    await self.publish_rpc_response(response_topic, telemetry)
                    print(f"Device {device_id}: Sent Temperature Sensor checkStatus via RPC")
                    data = f"device_data,sensor={sensor_tag},source=simulator temperature={temperature},received_timestamp={received_timestamp} {received_timestamp}"
                    if sensor_tag:
                        await send_influx(data)
                    else:
                        print(f"Skipping Influx write: device {device_id} has no token")

            elif device_type in self.SOILHUMIDITY_SENSOR or device_type == "soil humidity sensor":
                if method == "checkStatus":
                    current_state = device.state or {}
                    humidity = current_state.get("humidity", 50.0)
                    humidity += random.uniform(-2, 2)
                    humidity = max(0, min(100, humidity))
                    new_state = {"humidity": humidity}
                    device.state = new_state
                    await sync_to_async(device.save)()
                    telemetry = json.dumps(new_state)
                    await self.publish_rpc_response(response_topic, telemetry)
                    print(f"Device {device_id}: Sent Soil Humidity Sensor checkStatus via RPC")
                    data = f"device_data,sensor={sensor_tag},source=simulator humidity={humidity},received_timestamp={received_timestamp} {received_timestamp}"
                    if sensor_tag:
                        await send_influx(data)
                    else:
                        print(f"Skipping Influx write: device {device_id} has no token")

            elif device_type in self.PUMP or device_type == "pump":
                if method == "switchPump":
                    new_status = bool(params)
                    device.state = {"status": new_status}
                    await sync_to_async(device.save)()
                    telemetry = json.dumps({"status": new_status})
                    await self.mqtt_client.publish("v1/devices/me/telemetry", telemetry)
                    print(f"Device {device_id}: Pump updated to {new_status} via RPC")
                    data = f"device_data,sensor={sensor_tag},source=simulator status={float(1.0 if new_status else 0.0)},received_timestamp={received_timestamp} {received_timestamp}"
                    if sensor_tag:
                        await send_influx(data)
                    else:
                        print(f"Skipping Influx write: device {device_id} has no token")
                    await self.publish_rpc_response(response_topic, json.dumps({"status": new_status}))
                if method == "checkStatus":
                    telemetry = device.state.get("status", False)
                    await self.publish_rpc_response(response_topic, json.dumps({"status": telemetry}))

            elif device_type in self.POOL or device_type == "pool":
                if method == "switchPool":
                    new_status = bool(params)
                    device.state = {"status": new_status}
                    await sync_to_async(device.save)()
                    telemetry = json.dumps({"status": new_status})
                    await self.mqtt_client.publish("v1/devices/me/telemetry", telemetry)
                    print(f"Device {device_id}: Pool updated to {new_status} via RPC")
                    data = f"device_data,sensor={sensor_tag},source=simulator status={float(1.0 if new_status else 0.0)},received_timestamp={received_timestamp} {received_timestamp}"
                    if sensor_tag:
                        await send_influx(data)
                    else:
                        print(f"Skipping Influx write: device {device_id} has no token")
                    await self.publish_rpc_response(response_topic, json.dumps({"status": new_status}))
                if method == "checkStatus":
                    telemetry = device.state.get("status", False)
                    await self.publish_rpc_response(response_topic, json.dumps({"status": telemetry}))

            elif device_type in self.IRRIGATION or device_type == "irrigation":
                if method == "switchIrrigation":
                    new_status = bool(params)
                    device.state = {"status": new_status}
                    await sync_to_async(device.save)()
                    telemetry = json.dumps({"status": new_status})
                    await self.mqtt_client.publish("v1/devices/me/telemetry", telemetry)
                    print(f"Device {device_id}: Irrigation updated to {new_status} via RPC")
                    data = f"device_data,sensor={sensor_tag},source=simulator status={float(1.0 if new_status else 0.0)},received_timestamp={received_timestamp} {received_timestamp}"
                    if sensor_tag:
                        await send_influx(data)
                    else:
                        print(f"Skipping Influx write: device {device_id} has no token")
                    await self.publish_rpc_response(response_topic, json.dumps({"status": new_status}))
                if method == "checkStatus":
                    telemetry = device.state.get("status", False)
                    await self.mqtt_client.publish(response_topic, json.dumps({"status": telemetry}))

            elif device_type in self.AIR_CONDITIONER or device_type == "airconditioner":
                if method == "checkStatus":
                    current_state = device.state or {}
                    temperature = current_state.get("temperature", 24.0)
                    humidity = current_state.get("humidity", 50.0)
                    status = current_state.get("status", False)
                    # Simula pequenas variações
                    temperature += random.uniform(-0.5, 0.5)
                    humidity += random.uniform(-1, 1)
                    temperature = max(0, temperature)
                    humidity = max(0, min(100, humidity))
                    new_state = {
                        "temperature": temperature,
                        "humidity": humidity,
                        "status": status
                    }
                    device.state = new_state
                    await sync_to_async(device.save)()
                    telemetry = json.dumps(new_state)
                    await self.mqtt_client.publish(response_topic, telemetry)
                    print(f"Device {device_id}: Sent AirConditioner checkStatus via RPC")
                    data = f"device_data,sensor={sensor_tag},source=simulator temperature={temperature},humidity={humidity},status={float(1.0 if status else 0.0)},received_timestamp={received_timestamp} {received_timestamp}"
                    if sensor_tag:
                        await send_influx(data)
                    else:
                        print(f"Skipping Influx write: device {device_id} has no token")
                if method == "switchStatus":
                    new_status = bool(params)
                    current_state = device.state or {}
                    device.state = {
                        "temperature": current_state.get("temperature", 24.0),
                        "humidity": current_state.get("humidity", 50.0),
                        "status": new_status
                    }
                    await sync_to_async(device.save)()
                    telemetry = json.dumps(device.state)
                    await self.mqtt_client.publish("v1/devices/me/telemetry", telemetry)
                    print(f"Device {device_id}: AirConditioner status updated to {new_status} via RPC")
                    data = f"device_data,sensor={sensor_tag},source=simulator status={float(1.0 if new_status else 0.0)},received_timestamp={received_timestamp} {received_timestamp}"
                    if sensor_tag:
                        await send_influx(data)
                    else:
                        print(f"Skipping Influx write: device {device_id} has no token")
                    await self.mqtt_client.publish(response_topic, json.dumps({"status": new_status}))
            else:
                print(f"Device {device_id}: Unsupported device type for RPC.")
        except Exception as e:
            print(f"Device {self.token}: Error processing RPC message: {e}")

    async def publish(self, payload):
        try:
            await self.mqtt_client.publish("v1/devices/me/telemetry", payload)
        except Exception as e:
            # Handle publish failure: try a reconciliation (refresh token) and reconnect once
            print(f"[mqtt] publish failed for {self.device_id}: {e}. Trying reconciliation and reconnect...")
            try:
                device = await sync_to_async(Device.objects.get)(pk=self.device_pk)
                await sync_to_async(device.save)()
                await sync_to_async(device.refresh_from_db)()
                new_token = device.token
                if new_token and new_token != self.token:
                    self.token = new_token
                    self.client_id = new_token
                # attempt reconnect
                await self.connect()
                # retry publish once
                await self.mqtt_client.publish("v1/devices/me/telemetry", payload)
                return
            except Exception as re:
                print(f"[mqtt] reconciliação/republish falhou para {self.device_id}: {re}")
                # swallow exception to avoid killing whole loop
                return

    async def publish_rpc_response(self, topic, payload, retries=1):
        """Publish an RPC response, with a single reconnect+retry if the client is disconnected."""
        try:
            await self.mqtt_client.publish(topic, payload)
            print(f"Published RPC response to {topic}: {payload}")
            
            # Log the response timestamp for M2S latency measurement
            try:
                response_timestamp = int(time.time() * 1000)
                raw_token = getattr(self, 'thingsboard_id', None)
                if raw_token:
                    sensor_tag = str(raw_token).replace('\\', '\\\\').replace(',', '\\,').replace(' ', '\\ ').replace('=', '\\=')
                    # Write M2S received_timestamp to InfluxDB for latency calculation
                    influx_data = f"device_data,sensor={sensor_tag},source=simulator_response received_timestamp={response_timestamp} {response_timestamp}"
                    await post_to_influx(self.session, influx_data, None)
            except Exception:
                # Swallow logging errors to avoid affecting RPC response
                import traceback
                traceback.print_exc()
            
            return True
        except Exception as e:
            print(f"Publish RPC response failed for {topic}: {e}; attempting reconnect and retry...")
            try:
                # attempt reconnect
                await self.connect()
                await self.mqtt_client.publish(topic, payload)
                print(f"Published RPC response to {topic} after reconnect: {payload}")
                
                # Log the response timestamp for M2S latency measurement (retry case)
                try:
                    response_timestamp = int(time.time() * 1000)
                    raw_token = getattr(self, 'thingsboard_id', None)
                    if raw_token:
                        sensor_tag = str(raw_token).replace('\\', '\\\\').replace(',', '\\,').replace(' ', '\\ ').replace('=', '\\=')
                        # Write M2S received_timestamp to InfluxDB for latency calculation
                        influx_data = f"device_data,sensor={sensor_tag},source=simulator_response received_timestamp={response_timestamp} {response_timestamp}"
                        await post_to_influx(self.session, influx_data, None)
                except Exception:
                    # Swallow logging errors to avoid affecting RPC response
                    import traceback
                    traceback.print_exc()
                
                return True
            except Exception as e2:
                print(f"Failed to publish RPC response after reconnect for {topic}: {e2}")
                return False

    async def send_telemetry_async(self, use_influxdb=False, session=None):
        device_id = self.device_id
        device_type = self.device_type
        telemetry = None

        if self.use_memory:
            state = DEVICE_STATE[device_id]
        else:
            device = await sync_to_async(Device.objects.get)(pk=self.device_pk)
            await sync_to_async(device.refresh_from_db)()
            state = device.state or {}
            device_type = await sync_to_async(lambda d: d.device_type.name.lower())(device)

        if self.randomize:
            if device_type in self.LIGHTS:
                new_status = bool(random.getrandbits(1))
                if self.use_memory:
                    DEVICE_STATE[device_id]['status'] = new_status
                else:
                    device.state = {"status": new_status}
                    await sync_to_async(device.save)()
                telemetry = json.dumps({"status": new_status})
            elif device_type in self.AIR_CONDITIONER + self.TEMPERATURE_SENSOR:
                temperature = round(random.uniform(16, 28), 2)
                humidity = round(random.uniform(50, 80), 2)
                status = bool(random.getrandbits(1))
                if self.use_memory:
                    DEVICE_STATE[device_id] = {"temperature": temperature, "humidity": humidity, "status": status}
                else:
                    device.state = {"temperature": temperature, "humidity": humidity, "status": status}
                    await sync_to_async(device.save)()
                telemetry = json.dumps({"temperature": temperature, "humidity": humidity, "status": status})
            elif device_type in self.PUMP:
                status = bool(random.getrandbits(1))
                if self.use_memory:
                    DEVICE_STATE[device_id]['status'] = status
                else:
                    device.state = {"status": status}
                    await sync_to_async(device.save)()
                telemetry = json.dumps({"status": status})
            elif device_type in self.POOL:
                status = bool(random.getrandbits(1))
                if self.use_memory:
                    DEVICE_STATE[device_id]['status'] = status
                else:
                    device.state = {"status": status}
                    await sync_to_async(device.save)()
                telemetry = json.dumps({"status": status})
            elif device_type in self.IRRIGATION:
                status = bool(random.getrandbits(1))
                if self.use_memory:
                    DEVICE_STATE[device_id]['status'] = status
                else:
                    device.state = {"status": status}
                    await sync_to_async(device.save)()
                telemetry = json.dumps({"status": status})
            else:
                telemetry = json.dumps(state)
        else:
            if device_type in self.LIGHTS:
                status = DEVICE_STATE[device_id].get("status", False) if self.use_memory else state.get("status", False)
                telemetry = json.dumps({"status": status})
            else:
                telemetry = json.dumps(DEVICE_STATE[device_id] if self.use_memory else state)

        # Capture S2M sent_timestamp precisely when telemetry is sent
        sent_timestamp = int(time.time() * 1000)
        await self.publish(telemetry)
        print(f"Device {device_id}: Telemetry sent: {telemetry} at {sent_timestamp}")

        if use_influxdb and session is not None:
            headers = {
                "Authorization": f"Token {INFLUXDB_TOKEN}",
                "Content-Type": "text/plain",
            }
            timestamp = sent_timestamp  # Use precise sent_timestamp
            # determine sensor tag from token and sanitize
            device_obj = None
            try:
                device_obj = await sync_to_async(Device.objects.get)(pk=self.device_pk)
            except Exception:
                device_obj = None
            raw_token = getattr(self, 'thingsboard_id', None)
            if raw_token:
                sensor_tag = str(raw_token).replace('\\', '\\\\').replace(',', '\\,').replace(' ', '\\ ').replace('=', '\\=')
            else:
                sensor_tag = None
            if device_type in ["temperature sensor", "dht22", "airconditioner"]:
                state = DEVICE_STATE[device_id] if self.use_memory else state
                status = state.get("status", False)
                temperature = state.get("temperature", 0)
                humidity = state.get("humidity", 0)
                data = f"device_data,sensor={sensor_tag},source=simulator,direction=S2M status={float(1.0 if status else 0.0)},temperature={temperature},humidity={humidity},sent_timestamp={timestamp} {timestamp}"
            elif device_type in ["led", "lightbulb"]:
                state = DEVICE_STATE[device_id] if self.use_memory else state
                status = state.get("status", False)
                data = f"device_data,sensor={sensor_tag},source=simulator,direction=S2M status={float(1.0 if status else 0.0)},sent_timestamp={timestamp} {timestamp}"
            elif device_type in ["soilhumidity sensor", "soil humidity sensor"]:
                state = DEVICE_STATE[device_id] if self.use_memory else state
                status = state.get("status", False)
                humidity = state.get("humidity", 0)
                data = f"device_data,sensor={sensor_tag},source=simulator,direction=S2M status={float(1.0 if status else 0.0)},humidity={humidity},sent_timestamp={timestamp} {timestamp}"
            elif device_type in ["pump", "pool", "irrigation"]:
                state = DEVICE_STATE[device_id] if self.use_memory else state
                status = state.get("status", False)
                data = f"device_data,sensor={sensor_tag},source=simulator,direction=S2M status={float(1.0 if status else 0.0)},sent_timestamp={timestamp} {timestamp}"
            else:
                state = DEVICE_STATE[device_id] if self.use_memory else state
                status = state.get("status", False)
                data = f"device_data,sensor={sensor_tag},source=simulator,direction=S2M status={float(1.0 if status else 0.0)},sent_timestamp={timestamp} {timestamp}"
            # use helper that prints device fields and the payload
            try:
                status_code, text = await post_to_influx(session, data, device=device_obj)
                if status_code != 204 and status_code != 200:
                    print(f"Error sending data to InfluxDB: {status_code} - {text}")
            except Exception:
                print("Failed to post to InfluxDB; see debug above")

async def telemetry_task(publisher, use_influxdb, session):
    await publisher.connect()
    while True:
        await publisher.send_telemetry_async(use_influxdb=use_influxdb, session=session)
        await asyncio.sleep(HEARTBEAT_INTERVAL)

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
        parser.add_argument(
            '--system',
            type=str,
            help='Specify a system name to send telemetry only for its devices'
        )
        parser.add_argument(
            '--device-type',
            type=str,
            help='Specify a device type to send telemetry only for its devices'
        )
        parser.add_argument(
            '--memory',
            action='store_true',
            help='Use in-memory storage for device state (syncs to DB on exit)'
        )

    def handle(self, *args, **options):
        use_influxdb = options['use_influxdb']
        randomize = options['randomize']
        device_ids = options['device_id']
        system_name = options.get('system')
        device_type = options.get('device_type')
        use_memory = options['memory']

        if device_ids:
            all_devices = Device.objects.filter(id__in=device_ids)
        elif system_name:
            all_devices = Device.objects.filter(system__name=system_name)
        elif device_type:
            all_devices = Device.objects.filter(device_type__name__iexact=device_type)
        else:
            all_devices = Device.objects.all()

        if not all_devices:
            self.stdout.write("No devices registered.")
            return

        # Inicializa DEVICE_STATE a partir do banco se for usar memória
        if use_memory:
            device_type_map = {}
            for device in all_devices:
                DEVICE_STATE[device.device_id] = device.state or {}
                # Resolva o tipo do device ANTES do contexto async
                device_type_map[device.device_id] = device.device_type.name.lower() if device.device_type else ""
        else:
            device_type_map = {device.device_id: device.device_type.name.lower() if device.device_type else "" for device in all_devices}

        self.stdout.write("Starting async telemetry sending and waiting for RPCs...")

        async def main():
            async with aiohttp.ClientSession() as session:
                publishers = {}
                tasks = {}

                async def ensure_publisher_for_device(device):
                    if device.device_id in publishers:
                        return
                    pub = await TelemetryPublisher.create(
                        device,
                        randomize=randomize,
                        session=session,
                        use_memory=use_memory,
                        device_type_name=device_type_map.get(device.device_id, "")
                    )
                    publishers[device.device_id] = pub
                    tasks[device.device_id] = asyncio.create_task(telemetry_task_with_log(pub, use_influxdb, session))

                # Initialize publishers for current devices
                for device in all_devices:
                    await ensure_publisher_for_device(device)

                async def device_watcher():
                    # Periodically check for new devices and add publishers dynamically
                    while True:
                        await asyncio.sleep(5)
                        db_devices = await sync_to_async(list)(Device.objects.all())
                        known_ids = set(publishers.keys())
                        # new devices
                        for d in db_devices:
                            if d.device_id not in known_ids:
                                print(f"[watcher] New device detected: {d.device_id} -> adding publisher")
                                # resolve type safely via sync_to_async to avoid SynchronousOnlyOperation
                                try:
                                    dtype = await sync_to_async(lambda inst: inst.device_type.name.lower() if inst.device_type else "")(d)
                                except Exception:
                                    dtype = ""
                                device_type_map[d.device_id] = dtype
                                await ensure_publisher_for_device(d)
                        # NOTE: we do not stop publishers for removed devices to keep behavior stable

                watcher_task = asyncio.create_task(device_watcher())

                try:
                    await asyncio.gather(*tasks.values(), watcher_task)
                except asyncio.CancelledError:
                    pass

        async def telemetry_task_with_log(publisher, use_influxdb, session):
            await publisher.connect()
            while True:
                start = time.time()
                await publisher.send_telemetry_async(use_influxdb=use_influxdb, session=session)
                elapsed = time.time() - start
                print(f"[{publisher.token}] Telemetry sent. Elapsed: {elapsed:.2f}s. Sleeping for {HEARTBEAT_INTERVAL}s.")
                await asyncio.sleep(HEARTBEAT_INTERVAL)

        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            self.stdout.write("Stopping telemetry sending and RPC processing.")
            # Ao encerrar, comite o estado em memória no banco
            if use_memory:
                self.stdout.write("Syncing in-memory device state to database...")
                # Use bulk_update para salvar todos os estados de uma vez
                for device in all_devices:
                    state = DEVICE_STATE[device.device_id]
                    device.state = state
                Device.objects.bulk_update(all_devices, ['state'])
                self.stdout.write("Sync complete.")
            self.stdout.write("Stopping telemetry sending and RPC processing.")
            # Ao encerrar, comite o estado em memória no banco
            if use_memory:
                self.stdout.write("Syncing in-memory device state to database...")
                # Use bulk_update para salvar todos os estados de uma vez
                for device in all_devices:
                    state = DEVICE_STATE[device.device_id]
                    device.state = state
                Device.objects.bulk_update(all_devices, ['state'])
                self.stdout.write("Sync complete.")
