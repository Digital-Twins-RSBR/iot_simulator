import random

class BaseRPCHandler:
    def __init__(self, device):
        self.device = device

    def handle(self, method, params):
        raise NotImplementedError("RPC method not implemented for this device.")

class LEDHandler(BaseRPCHandler):
    def handle(self, method, params):
        if method == "switchLed":
            # Expects params to be a boolean value
            status = bool(params)
            self.device.state = {"status": status}
            self.device.save()
            return {"status": status}
        elif method == "checkStatus":
            return self.device.state
        else:
            return {"error": "Unsupported RPC method for LED."}

class DHT22Handler(BaseRPCHandler):
    def handle(self, method, params):
        if method == "checkStatus":
            # Retrieves current state or sets default values
            current_state = self.device.state
            temperature = current_state.get("temperature", 25.0)
            humidity = current_state.get("humidity", 50.0)
            # Simulates small variations in values
            temperature += random.uniform(-0.5, 0.5)
            humidity += random.uniform(-1, 1)
            new_state = {"temperature": temperature, "humidity": humidity}
            self.device.state = new_state
            self.device.save()
            return new_state
        else:
            return {"error": "Unsupported RPC method for DHT22."}

# Maps the type name to the corresponding handler.
RPC_HANDLER_REGISTRY = {
    "led": LEDHandler,
    "dht22": DHT22Handler,
}
