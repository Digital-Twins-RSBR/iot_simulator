from django.core.management.base import BaseCommand
from django.db import OperationalError
from devices.models import Device
import time

class Command(BaseCommand):
    help = "Renomeia todos os devices deste simulador para House {sim_num} (ex: House 2, House 3, ...). Use após restore do banco."

    def add_arguments(self, parser):
        parser.add_argument('--sim', type=int, required=True, help='Número do simulador (ex: 1, 2, 3...)')
        parser.add_argument('--force', action='store_true', help='Força renomear mesmo se já houver prefixo')

    def handle(self, *args, **options):
        sim_num = options['sim']
        force = options['force']
        # Aguarda tabela pronta (em caso de restore/migrate em andamento)
        max_wait = 60
        waited = 0
        while True:
            try:
                # Tenta acessar qualquer dado para forçar validação da tabela
                _ = Device.objects.exists()
                break
            except OperationalError as e:
                if waited >= max_wait:
                    self.stdout.write(self.style.WARNING(f"Tabela devices_device indisponível após {max_wait}s: {e}. Abortando renomeio."))
                    return
                self.stdout.write(self.style.WARNING(f"Tabela ainda não pronta ({e}), aguardando 3s... ({waited}/{max_wait}s)"))
                time.sleep(3)
                waited += 3

        count = 0
        for device in Device.objects.all():
            novo_nome = device.device_id.replace("House 1", f"House {sim_num}")
            if device.device_id != novo_nome:
                device.device_id = novo_nome
                device.save()
                count += 1
                self.stdout.write(self.style.SUCCESS(f"Renomeado: {novo_nome}"))
            novo_nome_unit = device.unit.name.replace("House 1", f"House {sim_num}")
            if device.unit.name != novo_nome_unit:
                device.unit.name = novo_nome_unit
                device.unit.save()
        self.stdout.write(self.style.SUCCESS(f"{count} devices renomeados para House {sim_num}"))
