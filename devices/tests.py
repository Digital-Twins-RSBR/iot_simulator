from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from devices.models import GatewayIOT


class DashboardViewTests(TestCase):
	def setUp(self):
		self.user = get_user_model().objects.create_user(
			username='admin',
			password='secret123',
			is_staff=True,
			is_superuser=True,
		)
		GatewayIOT.objects.create(
			name='tb-main',
			base_url='http://thingsboard:8080',
			auth_method=GatewayIOT.AUTH_METHOD_API_KEY,
			api_key='dummy-key',
			is_active=True,
		)
		self.client.force_login(self.user)

	def test_dashboard_requires_staff_login_redirect_from_root(self):
		response = self.client.get(reverse('index'))
		self.assertEqual(response.status_code, 302)
		self.assertEqual(response.url, reverse('simulator-dashboard'))

	@patch('devices.views.get_runtime_status')
	def test_dashboard_status_returns_runtime_payload(self, mock_status):
		mock_status.return_value = {
			'is_running': False,
			'mode': 'stopped',
			'managed_pid': None,
			'active_pid': None,
			'processes': [],
			'log_path': '/tmp/log',
			'pid_path': '/tmp/pid',
			'updated_at': 123,
		}
		response = self.client.get(reverse('simulator-dashboard-status'))
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()['runtime']['mode'], 'stopped')

	@patch('devices.views.test_gateway_connection')
	@patch('devices.views.start_simulator')
	def test_dashboard_start_invokes_runtime_control(self, mock_start, mock_test_gateway):
		mock_test_gateway.return_value = (True, 'ok')
		mock_start.return_value = {'ok': True, 'message': 'started', 'runtime': {'is_running': True}}
		response = self.client.post(
			reverse('simulator-dashboard-start'),
			data='{"randomize": true, "memory": true, "use_influxdb": false}',
			content_type='application/json',
		)
		self.assertEqual(response.status_code, 200)
		mock_start.assert_called_once()
		mock_test_gateway.assert_called_once()

	@patch('devices.views.test_gateway_connection')
	def test_dashboard_check_gateway_endpoint(self, mock_test_gateway):
		mock_test_gateway.return_value = (True, 'ok')
		response = self.client.post(reverse('simulator-dashboard-check-gateway'))
		self.assertEqual(response.status_code, 200)
		self.assertTrue(response.json()['ok'])

	@patch('devices.views.test_gateway_connection')
	def test_dashboard_start_blocks_when_gateway_check_fails(self, mock_test_gateway):
		mock_test_gateway.return_value = (False, 'unauthorized')
		response = self.client.post(
			reverse('simulator-dashboard-start'),
			data='{"randomize": true, "memory": true, "use_influxdb": false}',
			content_type='application/json',
		)
		self.assertEqual(response.status_code, 409)
		self.assertEqual(response.json()['error'], 'gateway_connection_failed')

	def test_dashboard_start_requires_active_gateway(self):
		GatewayIOT.objects.all().update(is_active=False)
		response = self.client.post(
			reverse('simulator-dashboard-start'),
			data='{"randomize": true, "memory": true, "use_influxdb": false}',
			content_type='application/json',
		)
		self.assertEqual(response.status_code, 409)
		self.assertEqual(response.json()['error'], 'gateway_not_configured')

	@patch('devices.views.stop_simulator')
	def test_dashboard_stop_invokes_runtime_control(self, mock_stop):
		mock_stop.return_value = {'ok': True, 'message': 'stopped', 'runtime': {'is_running': False}}
		response = self.client.post(reverse('simulator-dashboard-stop'))
		self.assertEqual(response.status_code, 200)
		mock_stop.assert_called_once()


class GatewayIOTModelTests(TestCase):
	def test_save_active_gateway_disables_others(self):
		first = GatewayIOT.objects.create(
			name='gw-1',
			base_url='http://tb-1:8080',
			auth_method=GatewayIOT.AUTH_METHOD_API_KEY,
			api_key='key-1',
			is_active=True,
		)
		second = GatewayIOT.objects.create(
			name='gw-2',
			base_url='http://tb-2:8080',
			auth_method=GatewayIOT.AUTH_METHOD_API_KEY,
			api_key='key-2',
			is_active=True,
		)

		first.refresh_from_db()
		second.refresh_from_db()

		self.assertFalse(first.is_active)
		self.assertTrue(second.is_active)
