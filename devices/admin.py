from django.contrib import admin
from .models import DeviceType, Device, System, Unit

@admin.register(DeviceType)
class DeviceTypeAdmin(admin.ModelAdmin):
    list_display = ('name',)

@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_filter = ('device_type', 'system', 'unit')
    list_display = ('device_id', 'device_type', 'token', 'system', 'unit')

@admin.register(System)
class SystemAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', )

@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ('name', 'system')
