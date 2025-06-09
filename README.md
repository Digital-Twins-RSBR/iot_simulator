# IOT Simulator

The **IOT Simulator** is a tool developed in Django to simulate IoT devices that communicate with ThingsBoard. With it, you can register devices (via Django Admin) and then periodically send telemetry data to ThingsBoard via MQTT – simulating the behavior of physical devices (such as LEDs and DHT22 sensors). The tool also offers an interface to process RPC (Remote Procedure Call) calls and update the state of devices, facilitating integration with digital twin solutions and IoT middleware.

## Recent Changes

- **Import Devices from JSON**: Added a command to import device definitions directly from a JSON file, streamlining the process of adding multiple devices.
- **System and Unit Models**: Introduced new models named `System` and `Unit` to improve code organization and separation of concerns. Devices are now grouped under Units, and Units are grouped under Systems.

## Project Components

### 1. Models
- **DeviceType**: Defines the type of device (e.g., "led" or "dht22"). Each type can have a default implementation of RPC methods.
- **Device**: Represents an IoT device, storing the `device_id`, `token` (for authentication with ThingsBoard), and the current state (stored in a JSON field).

### 2. RPC Handlers
Each device type has a handler responsible for implementing the default RPC methods:
- **LEDHandler**: Implements the methods `"switchLed"` (to turn the LED on/off) and `"checkStatus"` (to return the current status).
- **DHT22Handler**: Implements the `"checkStatus"` method, which simulates temperature and humidity readings, updating the values with random variations.

A registry (`RPC_HANDLER_REGISTRY`) maps the device type name to the corresponding handler.

### 3. Endpoints and Communication with ThingsBoard
- **RPC Endpoint**: Exposed at `/devices/rpc/<device_id>/` via POST method. This endpoint receives a JSON payload with the RPC method and parameters, forwards the call to the corresponding handler, and returns the response.
- **Telemetry Management Command**: A Django command (`send_telemetry`) that, based on the registered devices, periodically (every 10 seconds) sends telemetry data to ThingsBoard using the MQTT protocol. This functionality simulates the `loop()` of a physical device.

### 4. Integration with Django Admin
Use the Django Admin interface to:
- Register **DeviceTypes** (e.g., "led" and "dht22").
- Register **Devices** by associating each device with its type, defining the `device_id`, `token`, and initial state.

## How to Use the IOT Simulator

### Prerequisites
- Python 3.7+ (recommended)
- Django (3.1 or higher)
- paho-mqtt

### Installation and Configuration
1. **Clone the Repository and Create the Virtual Environment:**
   ```bash
   git clone <REPOSITORY_URL>
   cd iot-simulator
   python -m venv venv
   source venv/bin/activate  # or venv\Scripts\activate on Windows
   ```
2. **Install the Dependencies**:
    ```bash
    pip install -Ur requirements/base.txt
    ```
3. Configure the Django Project
    - Make the necessary database and other configurations in the myproject/settings.py file as needed
    - Run the migrations:
    ```bash
    python manage.py migrate
    ```
4. Create a Superuser to Access the Admin:
    ```bash
    python manage.py createsuperuser
    ```

### Using the IOT Simulator

#### Registering Devices
1. Access the Django Admin:
    - Start the server:
    ```bash
    python manage.py runserver
    ```
    - Access http://localhost:<port>/admin/ and log in with the created superuser.
2. Register Device Types
    - Create entries in DeviceType (e.g., led and dht22)
3. Register Devices
    - In Device, register each device by providing:
        - device_id: Unique identifier of the device.
        - device_type: Select the corresponding type.
        - token: Token used for authentication with ThingsBoard.
        - state: Initial state (e.g., {"status": false} for an LED or {"temperature": 25.0, "humidity": 50.0} for a sensor).

### Configuration in ThingsBoard
1. Access ThingsBoard:
    - Use demo.thingsboard.io or your local instance.
2. Register Devices in ThingsBoard:
    - Create a device in ThingsBoard for each device registered in Django.
    - Configure the device token in ThingsBoard exactly as registered in Django.
    - Ensure that the device in ThingsBoard is configured to receive telemetry on the default topic v1/devices/me/telemetry and RPC calls on the request/response topics.

### Running the Telemetry Simulation
1. Start the Telemetry Command:
    - In a terminal, run:
    ```bash
    python manage.py send_telemetry
    ```
    - This command will connect each device to ThingsBoard via MQTT and periodically send telemetry data (every 10 seconds), simulating the continuous operation of the devices.
2. Check the Data in ThingsBoard:
    - In the ThingsBoard dashboard, view the telemetry data and RPC calls to confirm that the simulated devices are communicating correctly.

### Extensibility
    - New Device Types:
    To add new types, create a new handler in devices/rpc_handlers.py implementing the desired RPC methods and add it to the RPC_HANDLER_REGISTRY.
    - Additional Endpoints:
    It is possible to extend the API with new endpoints to, for example, receive additional commands, configure telemetry intervals, or integrate other functionalities.


### How the Telemetry and Property Synchronization Process Works:

#### Connection and Subscription for RPC:
- Each instance of TelemetryPublisher creates an MQTT client using the device's token and registers the on_connect and on_message callbacks.
    In on_connect, the client subscribes to the topic v1/devices/me/rpc/request/+ to receive RPC calls sent by ThingsBoard.
    The on_message processes the received message, differentiating the behavior for devices of type led (e.g., processing the "switchLed" or "checkStatus" method) and dht22 (processing "checkStatus").

#### Sending Telemetry:
    - The send_telemetry() method reloads the device from the database (to reflect changes made via Django Admin), simulates any variations (in the case of the DHT22 sensor), and sends the payload via MQTT.

    - Synchronization Loop Every 5 Seconds:
    In the command, the main loop iterates over all devices and calls send_telemetry() every 5 seconds. Thus, in addition to sending telemetry data, the device remains “listening” for RPC messages and responding to them as needed.

When running the command:
    ```bash
    python manage.py send_telemetry
    ```
each device will be connected to ThingsBoard, periodically send telemetry, and wait (and process) RPC calls that may change its state or request information.
This approach ensures that both updates made via Admin and calls from ThingsBoard are reflected and synchronized in real-time.

When running the command:
```bash
python manage.py send_telemetry --device-id device1 device2 --use-influxdb --randomize
```
You can specify the devices identifiers and if you want use a influxdb to store all the sended values and the parameter randomize to make randomized values from devices