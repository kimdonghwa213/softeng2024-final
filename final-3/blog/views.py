from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import requests
import json
import math

def home(request):
    """홈페이지 뷰"""
    return render(request, 'blog/home.html')

def calculate_vpd(temperature, humidity):
    """
    VPD 계산 함수
    temperature: 온도 (°C)
    humidity: 상대습도 (%)
    returns: VPD (kPa)
    """
    try:
        # 포화수증기압 계산 (kPa)
        svp = 0.61078 * math.exp(17.27 * temperature / (temperature + 237.3))
        # 실제수증기압 계산 (kPa)
        avp = svp * (humidity / 100.0)
        # VPD 계산 (kPa)
        vpd = svp - avp
        return round(vpd, 2)
    except:
        return None

def get_flask_data():
    """Flask 서버에서 센서 데이터 가져오기"""
    url = "http://113.198.63.27:21350/data"  # Flask 서버 주소
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            # VPD 계산 추가
            temperature = float(data.get('temperature', 0))
            humidity = float(data.get('humidity', 0))
            data['vpd'] = calculate_vpd(temperature, humidity)
            return data
        else:
            return {
                "temperature": "N/A",
                "humidity": "N/A",
                "vpd": "N/A",
                "motor_state": "N/A",
                "min_vpd": 0.8,
                "max_vpd": 1.2
            }
    except requests.exceptions.RequestException:
        return {
            "temperature": "N/A",
            "humidity": "N/A",
            "vpd": "N/A",
            "motor_state": "N/A",
            "min_vpd": 0.8,
            "max_vpd": 1.2
        }

def sensor_data(request):
    """센서 데이터 페이지 뷰"""
    data = get_flask_data()
    return render(request, 'blog/sensor_data.html', {'data': data})

def get_sensor_data_api(request):
    """센서 데이터 API 뷰"""
    data = get_flask_data()
    return JsonResponse(data)

def vpd_control(request):
    """VPD 설정 페이지 뷰"""
    data = get_flask_data()
    vpd_settings = {
        'min_vpd': data.get('min_vpd', 0.8),
        'max_vpd': data.get('max_vpd', 1.2)
    }
    return render(request, 'blog/vpd_settings.html', {
        'data': data,
        'vpd_settings': vpd_settings
    })

@csrf_exempt
def update_vpd_settings(request):
    """VPD 설정 업데이트 API 뷰"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            # Flask 서버로 설정 전송
            response = requests.post('http://113.198.63.27:21350/update-vpd-settings', json=data)
            return JsonResponse(response.json())
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

def check_vpd_status(request):
    """VPD 상태 확인 API 뷰"""
    data = get_flask_data()
    return JsonResponse(data)