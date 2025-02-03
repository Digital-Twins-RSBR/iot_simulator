import random

class BaseRPCHandler:
    def __init__(self, device):
        self.device = device

    def handle(self, method, params):
        raise NotImplementedError("Método RPC não implementado para este dispositivo.")

class LEDHandler(BaseRPCHandler):
    def handle(self, method, params):
        if method == "switchLed":
            # Espera que params seja um valor booleano
            status = bool(params)
            self.device.state = {"status": status}
            self.device.save()
            return {"status": status}
        elif method == "checkStatus":
            return self.device.state
        else:
            return {"error": "Método RPC não suportado para LED."}

class DHT22Handler(BaseRPCHandler):
    def handle(self, method, params):
        if method == "checkStatus":
            # Recupera estado atual ou define valores padrões
            current_state = self.device.state
            temperature = current_state.get("temperature", 25.0)
            humidity = current_state.get("humidity", 50.0)
            # Simula pequenas variações nos valores
            temperature += random.uniform(-0.5, 0.5)
            humidity += random.uniform(-1, 1)
            new_state = {"temperature": temperature, "humidity": humidity}
            self.device.state = new_state
            self.device.save()
            return new_state
        else:
            return {"error": "Método RPC não suportado para DHT22."}

# Mapeia o nome do tipo para o handler correspondente.
RPC_HANDLER_REGISTRY = {
    "led": LEDHandler,
    "dht22": DHT22Handler,
}
