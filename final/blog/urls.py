# blog/urls.py

from django.urls import path
from . import views

app_name = 'blog'

urlpatterns = [
    path('', views.home, name='home'),
    path('sensor/', views.sensor_data, name='sensor_data'),
    path('vpd-settings/', views.vpd_control, name='vpd_settings'),
    path('get-sensor-data/', views.get_sensor_data_api, name='get_sensor_data_api'),
    path('update-vpd-settings/', views.update_vpd_settings, name='update_vpd_settings'),
    path('check-vpd-status/', views.check_vpd_status, name='check_vpd_status'),
]