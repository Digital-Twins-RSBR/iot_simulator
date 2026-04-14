from django.urls import path
from . import views

urlpatterns = [
	path('dashboard/', views.dashboard, name='simulator-dashboard'),
	path('api/dashboard/status/', views.dashboard_status, name='simulator-dashboard-status'),
	path('api/dashboard/start/', views.dashboard_start, name='simulator-dashboard-start'),
	path('api/dashboard/stop/', views.dashboard_stop, name='simulator-dashboard-stop'),
	path('api/dashboard/check-gateway/', views.dashboard_check_gateway, name='simulator-dashboard-check-gateway'),
	path('api/dashboard/logs/', views.dashboard_logs, name='simulator-dashboard-logs'),
]
