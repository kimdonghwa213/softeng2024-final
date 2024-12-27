from flask import Flask, jsonify, request
from gpiozero import OutputDevice, InputDevice, Motor, Servo, LED
import time
import math
import signal
import sys
import requests

app = Flask(__name__)

# Line Notify 설정
LINE_NOTIFY_TOKEN = "Zqtv7zXOqg90MJJ9zbb2i12G0xQyN4gr6wX0fywEOLO"
LINE_NOTIFY_API = "https://notify-api.line.me/api/notify"
LINE_HEADERS = {
    "Authorization": f"Bearer {LINE_NOTIFY_TOKEN}"
}

# VPD 상태 추적을 위한 변수
vpd_state = "NORMAL"  # "NORMAL", "LOW", "HIGH"

# 센서와 모터, LED 초기화
motor = Motor(forward=13, backward=27, enable=22)
led = LED(20)
dht11 = None

# 서보 모터 설정
myGPIO = 18
myCorrection = 0.45
maxPW = (2.0 + myCorrection) / 1000
minPW = (1.0 - myCorrection) / 1000
servo = Servo(myGPIO, min_pulse_width=minPW, max_pulse_width=maxPW)

# VPD 설정 기본값
vpd_settings = {
    'min_vpd': 0.8,
    'max_vpd': 1.2
}

# 상태 추적
motor_running = False
servo_position = "MID"
led_state = False


def send_line_notify(message):
    """Line Notify로 메시지 전송"""
    try:
        response = requests.post(
            LINE_NOTIFY_API,
            headers=LINE_HEADERS,
            data={'message': message}
        )
        return response.status_code == 200
    except Exception as e:
        print(f"Line Notify 전송 실패: {str(e)}")
        return False


# Ctrl+C 시그널 핸들러
def signal_handler(sig, frame):
    print('\n프로그램을 종료합니다...')
    servo.mid()
    led.off()
    time.sleep(0.5)
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)


class DHT11():
    MAX_DELAY_COUNT = 100
    BIT_1_DELAY_COUNT = 10
    BITS_LEN = 40
    MAX_RETRIES = 3  # 최대 재시도 횟수
    RETRY_DELAY = 2  # 재시도 간 대기 시간(초)

    def __init__(self, pin, pull_up=False):
        self._pin = pin
        self._pull_up = pull_up
        self._last_valid_humidity = None
        self._last_valid_temperature = None

    def read_data_with_retry(self):
        """센서 데이터를 읽고 실패시 재시도"""
        for attempt in range(self.MAX_RETRIES):
            humidity, temperature = self.read_data()

            # 유효한 데이터인지 확인
            if self.is_valid_reading(humidity, temperature):
                self._last_valid_humidity = humidity
                self._last_valid_temperature = temperature
                return humidity, temperature

            print(f"센서 읽기 실패 (시도 {attempt + 1}/{self.MAX_RETRIES})")
            if attempt < self.MAX_RETRIES - 1:  # 마지막 시도가 아니면 대기
                time.sleep(self.RETRY_DELAY)

        # 모든 재시도 실패 시 마지막 유효값 반환
        if self._last_valid_humidity is not None and self._last_valid_temperature is not None:
            print("최근 유효한 데이터 사용")
            return self._last_valid_humidity, self._last_valid_temperature

        print("센서 읽기 완전 실패")
        return None, None

    def is_valid_reading(self, humidity, temperature):
        """센서 값이 유효한지 확인"""
        if humidity is None or temperature is None:
            return False
        if not (0 <= humidity <= 100) or not (-40 <= temperature <= 80):
            return False
        return True

    def read_data(self):
        """센서 데이터 읽기"""
        try:
            bit_count = 0
            delay_count = 0
            bits = ""

            # 센서 초기화
            gpio = OutputDevice(self._pin)
            gpio.off()
            time.sleep(0.02)  # 20ms 대기

            gpio.close()
            gpio = InputDevice(self._pin, pull_up=self._pull_up)

            # 센서 응답 대기
            timeout = time.time() + 1.0  # 1초 타임아웃
            while gpio.value == 1:
                if time.time() > timeout:
                    return None, None
                pass

            # 데이터 비트 읽기
            while bit_count < self.BITS_LEN:
                timeout = time.time() + 1.0

                # 0 신호 대기
                while gpio.value == 0:
                    if time.time() > timeout:
                        return None, None
                    pass

                # 1 신호 길이 측정
                while gpio.value == 1:
                    delay_count += 1
                    if delay_count > self.MAX_DELAY_COUNT:
                        break
                    if time.time() > timeout:
                        return None, None

                if delay_count > self.BIT_1_DELAY_COUNT:
                    bits += "1"
                else:
                    bits += "0"

                delay_count = 0
                bit_count += 1

            # 데이터 파싱
            if len(bits) >= 40:
                humidity_integer = int(bits[0:8], 2)
                humidity_decimal = int(bits[8:16], 2)
                temperature_integer = int(bits[16:24], 2)
                temperature_decimal = int(bits[24:32], 2)
                check_sum = int(bits[32:40], 2)

                _sum = humidity_integer + humidity_decimal + temperature_integer + temperature_decimal

                if check_sum == _sum:
                    humidity = float(f'{humidity_integer}.{humidity_decimal}')
                    temperature = float(f'{temperature_integer}.{temperature_decimal}')
                    return humidity, temperature

            return None, None

        except Exception as e:
            print(f"센서 읽기 오류: {str(e)}")
            return None, None


def calculate_vpd(temperature, humidity):
    """VPD 계산 함수"""
    try:
        if temperature is None or humidity is None:
            return None
        svp = 0.61078 * math.exp(17.27 * temperature / (temperature + 237.3))
        avp = svp * (humidity / 100.0)
        vpd = svp - avp
        return round(vpd, 2)
    except:
        return None


def check_and_control_devices(vpd, temperature, humidity):
    """VPD 값을 확인하고 모터, 서보, LED를 제어하는 함수"""
    global motor_running, servo_position, led_state, vpd_state

    if vpd is None:
        return "ERROR"

    # VPD가 너무 낮을 때
    if vpd < vpd_settings['min_vpd']:
        if vpd_state != "LOW":
            message = (f"\nVPD 경고: 너무 낮음"
                       f"\nVPD: {vpd} kPa"
                       f"\n설정된 최소값: {vpd_settings['min_vpd']} kPa"
                       f"\n온도: {temperature}°C"
                       f"\n습도: {humidity}%"
                       f"\n동작: 유동팬(Fan)이 작동하고, 측창이 개방됩니다.")
            send_line_notify(message)
            vpd_state = "LOW"

        if not motor_running:
            motor.forward()
            servo.max()
            motor_running = True
            servo_position = "MAX"
        led.off()
        led_state = False
        return "RUNNING (LOW VPD)"

    # VPD가 너무 높을 때
    elif vpd > vpd_settings['max_vpd']:
        if vpd_state != "HIGH":
            message = (f"\nVPD 경고: 너무 높음"
                       f"\nVPD: {vpd} kPa"
                       f"\n설정된 최대값: {vpd_settings['max_vpd']} kPa"
                       f"\n온도: {temperature}°C"
                       f"\n습도: {humidity}%"
                       f"\n동작: 포그기(Fog system)가 작동됩니다.")
            send_line_notify(message)
            vpd_state = "HIGH"

        if motor_running:
            motor.stop()
            servo.mid()
            motor_running = False
            servo_position = "MID"
        led.on()
        led_state = True
        return "LED ON (HIGH VPD)"

    # VPD가 정상 범위일 때
    else:
        if vpd_state != "NORMAL":
            message = (f"\nVPD 상태: 정상 범위로 복귀"
                       f"\nVPD: {vpd} kPa"
                       f"\n설정 범위: {vpd_settings['min_vpd']} ~ {vpd_settings['max_vpd']} kPa"
                       f"\n온도: {temperature}°C"
                       f"\n습도: {humidity}%")
            send_line_notify(message)
            vpd_state = "NORMAL"

        if motor_running:
            motor.stop()
            servo.mid()
            motor_running = False
            servo_position = "MID"
        led.off()
        led_state = False
        return "NORMAL"


@app.route('/data')
def get_data():
    humidity, temperature = dht11.read_data_with_retry()
    if humidity is None or temperature is None:
        return jsonify({
            "temperature": "N/A",
            "humidity": "N/A",
            "vpd": "N/A",
            "device_state": "ERROR",
            "motor_state": "STOPPED",
            "servo_state": "MID",
            "led_state": "OFF",
            "min_vpd": vpd_settings['min_vpd'],
            "max_vpd": vpd_settings['max_vpd']
        })

    vpd = calculate_vpd(temperature, humidity)
    device_state = check_and_control_devices(vpd, temperature, humidity)

    return jsonify({
        "temperature": temperature,
        "humidity": humidity,
        "vpd": vpd,
        "device_state": device_state,
        "motor_state": "RUNNING" if motor_running else "STOPPED",
        "servo_state": servo_position,
        "led_state": "ON" if led_state else "OFF",
        "min_vpd": vpd_settings['min_vpd'],
        "max_vpd": vpd_settings['max_vpd']
    })


@app.route('/update-vpd-settings', methods=['GET', 'POST'])
def update_vpd_settings():
    if request.method == 'GET':
        return jsonify(vpd_settings)

    try:
        data = request.get_json()
        vpd_settings['min_vpd'] = float(data['min_vpd'])
        vpd_settings['max_vpd'] = float(data['max_vpd'])
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400


if __name__ == '__main__':
    # 센서 초기화
    dht11 = DHT11(17)

    # 서보 모터 초기 위치 설정
    servo.mid()

    # LED 초기 상태 설정
    led.off()

    # 센서 안정화 시간
    time.sleep(5)

    # Flask 서버 시작
    app.run(host='0.0.0.0', port=5000, debug=False)