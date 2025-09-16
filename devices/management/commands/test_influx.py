import asyncio
import time
import traceback
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from devices.models import Device
import aiohttp
import os


INFLUXDB_HOST = getattr(settings, 'INFLUXDB_HOST', 'localhost')
INFLUXDB_PORT = getattr(settings, 'INFLUXDB_PORT', 8086)
INFLUXDB_BUCKET = getattr(settings, 'INFLUXDB_BUCKET', 'iot_data')
INFLUXDB_ORGANIZATION = getattr(settings, 'INFLUXDB_ORGANIZATION', '')
INFLUXDB_TOKEN = getattr(settings, 'INFLUXDB_TOKEN', '')
INFLUXDB_URL = f"http://{INFLUXDB_HOST}:{INFLUXDB_PORT}/api/v2/write?org={INFLUXDB_ORGANIZATION}&bucket={INFLUXDB_BUCKET}&precision=ms"


class Command(BaseCommand):
    help = 'Test InfluxDB write by creating a single point for a device.'

    def add_arguments(self, parser):
        parser.add_argument('--device-id', required=True, help='device.device_id to write the test point for')
        parser.add_argument('--value', type=float, default=1.0, help='numeric value to write')
        parser.add_argument('--measurement', default='device_data', help='measurement name')
        parser.add_argument('--field', default='test_value', help='field key name')

    def handle(self, *args, **options):
        device_id = options['device_id']
        value = options['value']
        measurement = options['measurement']
        field = options['field']

        # Verify device exists (lookup by device_id) and has a thingsboard_id
        try:
            device = Device.objects.get(device_id=device_id)
        except Device.DoesNotExist:
            raise CommandError(f'Device with device_id={device_id} not found')

        token = getattr(device, 'token', None)
        if not token:
            raise CommandError(f'Device {device_id} has no token set. Cannot write to Influx without a valid token.')

        # sanitize token for line-protocol tag value
        sensor_tag = str(token).replace('\\', '\\\\').replace(',', '\\,').replace(' ', '\\ ').replace('=', '\\=')

        timestamp = int(time.time() * 1000)
        # Use token as canonical sensor tag for Influx
        line = f"{measurement},sensor={sensor_tag},source=simulator {field}={value},sent_timestamp={timestamp} {timestamp}"

        headers = {
            'Authorization': f'Token {INFLUXDB_TOKEN}',
            'Content-Type': 'text/plain'
        }

        async def do_write():
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.post(INFLUXDB_URL, headers=headers, data=line) as resp:
                        text = await resp.text()
                        if resp.status in (204, 200):
                            print(f'Point written successfully to InfluxDB (status={resp.status})')
                            print('Line protocol sent:')
                            print(line)
                        else:
                            print('InfluxDB returned error')
                            print(f'Status: {resp.status}')
                            print(f'Response body: {text}')
                            raise Exception(f'InfluxDB write failed with status {resp.status}')
                except Exception as e:
                    print('Exception during InfluxDB write:')
                    traceback.print_exc()
                    raise

        try:
            asyncio.run(do_write())
        except Exception as e:
            raise CommandError(f'Failed to write to InfluxDB: {e}')
