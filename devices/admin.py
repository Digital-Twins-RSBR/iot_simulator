from django.contrib import admin
from django.contrib import messages
from django.conf import settings
from django import forms
from .models import DeviceType, Device, System, Unit, GatewayIOT
from .simulator_control import start_simulator, stop_simulator
from .thingsboard_gateway import test_gateway_connection


class GatewayIOTAdminForm(forms.ModelForm):
    class Meta:
        model = GatewayIOT
        fields = '__all__'
        widgets = {
            'password': forms.PasswordInput(render_value=True),
            'api_key': forms.PasswordInput(render_value=True),
        }

@admin.register(DeviceType)
class DeviceTypeAdmin(admin.ModelAdmin):
    list_display = ('name',)

@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_filter = ('device_type', 'system', 'unit')
    list_display = ('device_id', 'device_type', 'token', 'system', 'unit')


@admin.register(GatewayIOT)
class GatewayIOTAdmin(admin.ModelAdmin):
    form = GatewayIOTAdminForm
    list_display = ('name', 'base_url', 'auth_method', 'is_active', 'updated_at')
    list_filter = ('is_active', 'auth_method')
    search_fields = ('name', 'base_url', 'username')
    actions = ('activate_gateway', 'check_gateway_access', 'start_sync', 'stop_sync')

    fieldsets = (
        ('Gateway', {
            'fields': ('name', 'is_active', 'base_url', 'mqtt_port', 'mqtt_keep_alive', 'auth_method'),
        }),
        ('Credenciais login/senha', {
            'fields': ('username', 'password'),
        }),
        ('API Key', {
            'fields': ('api_key',),
        }),
    )

    @admin.action(description='Ativar gateway selecionado')
    def activate_gateway(self, request, queryset):
        gateway = queryset.order_by('-updated_at').first()
        if not gateway:
            self.message_user(request, 'Selecione ao menos um gateway.', level=messages.WARNING)
            return
        GatewayIOT.objects.filter(is_active=True).exclude(pk=gateway.pk).update(is_active=False)
        gateway.is_active = True
        gateway.save(update_fields=['is_active', 'updated_at'])
        self.message_user(request, f"Gateway '{gateway.name}' ativado com sucesso.", level=messages.SUCCESS)

    @admin.action(description='Verificar acesso ao gateway')
    def check_gateway_access(self, request, queryset):
        gateways = list(queryset)
        if not gateways:
            self.message_user(request, 'Selecione ao menos um gateway.', level=messages.WARNING)
            return

        ok_count = 0
        for gateway in gateways:
            ok, detail = test_gateway_connection(gateway=gateway)
            if ok:
                ok_count += 1
                self.message_user(
                    request,
                    f"Gateway '{gateway.name}' acessivel e autenticado.",
                    level=messages.SUCCESS,
                )
            else:
                self.message_user(
                    request,
                    f"Gateway '{gateway.name}' sem acesso: {detail}",
                    level=messages.ERROR,
                )

        if ok_count == len(gateways):
            self.message_user(request, 'Todos os gateways selecionados foram validados.', level=messages.SUCCESS)

    @admin.action(description='Ligar sync (send_telemetry)')
    def start_sync(self, request, queryset):
        gateway = queryset.order_by('-updated_at').first() or GatewayIOT.objects.filter(is_active=True).first()
        if not gateway:
            self.message_user(request, 'Nenhum gateway selecionado/ativo para iniciar o sync.', level=messages.ERROR)
            return

        if not gateway.is_active:
            GatewayIOT.objects.filter(is_active=True).exclude(pk=gateway.pk).update(is_active=False)
            gateway.is_active = True
            gateway.save(update_fields=['is_active', 'updated_at'])

        ok, detail = test_gateway_connection(gateway=gateway)
        if not ok:
            self.message_user(
                request,
                f"Nao foi possivel iniciar o sync. Falha no gateway '{gateway.name}': {detail}",
                level=messages.ERROR,
            )
            return

        result = start_simulator(
            randomize=getattr(settings, 'SIMULATOR_RANDOMIZE_DEFAULT', True),
            use_memory=getattr(settings, 'SIMULATOR_MEMORY_DEFAULT', True),
            use_influxdb=bool(getattr(settings, 'INFLUXDB_TOKEN', '')),
        )
        message_level = messages.SUCCESS if result.get('ok') else messages.WARNING
        self.message_user(request, result.get('message', 'Comando de start executado.'), level=message_level)

    @admin.action(description='Desligar sync (send_telemetry)')
    def stop_sync(self, request, queryset):
        result = stop_simulator()
        message_level = messages.SUCCESS if result.get('ok') else messages.WARNING
        self.message_user(request, result.get('message', 'Comando de stop executado.'), level=message_level)

@admin.register(System)
class SystemAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', )

@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ('name', 'system')
