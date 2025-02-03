from django.contrib import admin
from .models import DeviceType, Device

@admin.register(DeviceType)
class DeviceTypeAdmin(admin.ModelAdmin):
    list_display = ('name',)

@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ('device_id', 'device_type', 'token')
