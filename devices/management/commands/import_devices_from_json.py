import json
import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from devices.models import Device, DeviceType, System, Unit

class Command(BaseCommand):
    help = "Import devices from a JSON template and create them under a system, replicating units (e.g., casas). Also creates devices in ThingsBoard."

    def add_arguments(self, parser):
        parser.add_argument('json_file', type=str, help='Path to the JSON file with device templates')
        parser.add_argument('--system', type=str, required=True, help='System name to assign devices')
        parser.add_argument('--replicas', type=int, default=1, help='How many units to replicate (e.g., casas)')

    def handle(self, *args, **options):
        json_file = options['json_file']
        system_name = options['system']
        replicas = options['replicas']

        with open(json_file, 'r') as f:
            template = json.load(f)

        system, _ = System.objects.get_or_create(name=system_name)

        for replica in range(1, replicas + 1):
            unit_name = f"{template.get('template_name', 'Unit')} {replica}"
            unit, _ = Unit.objects.get_or_create(name=unit_name, system=system)
            for dev in template['devices']:
                device_type, _ = DeviceType.objects.get_or_create(name=dev['device_type'])
                device_id = f"{dev['base_name']}_{replica}"

                # Verifica se o device já existe antes de criar
                if Device.objects.filter(device_id=device_id).exists():
                    self.stdout.write(self.style.WARNING(
                        f"Device '{device_id}' já existe. Pulando criação."
                    ))
                    continue

                Device.objects.create(
                    device_id=device_id,
                    device_type=device_type,
                    token="",  # Inicializa vazio, será preenchido depois
                    state=dev.get('state', {}),
                    system=system,
                    unit=unit
                )
                self.stdout.write(self.style.SUCCESS(
                    f"Created device '{device_id}' (local e ThingsBoard via model)"
                ))
        self.stdout.write(self.style.SUCCESS(f"Imported {replicas} units for system '{system_name}'"))
