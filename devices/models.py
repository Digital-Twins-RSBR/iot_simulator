from django.db import models

class DeviceType(models.Model):
    name = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True, null=True)
    
    def __str__(self):
        return self.name

class Device(models.Model):
    device_id = models.CharField(max_length=50, unique=True)
    device_type = models.ForeignKey(DeviceType, on_delete=models.CASCADE)
    token = models.CharField(max_length=100)
    # Campo para armazenar o estado do dispositivo (por exemplo, {"status": true} ou {"temperature": 25.0, "humidity": 50.0})
    state = models.JSONField(default=dict)  # Disponível no Django 3.1+; caso contrário, use um JSONField de um package específico.

    def __str__(self):
        return self.device_id
