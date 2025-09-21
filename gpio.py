import RPi.GPIO as GPIO
import time
import requests
import yaml
import os

# Настройки
BUTTON_PIN = 4
RPI_SERVER_IP = "127.0.0.1"
DEBOUNCE_TIME = 0.3
MEDIAMTX_FILE = "/etc/mediamtx.yml"
META_CONFIG_FILE = "/home/pi/camportal/cameras_meta.yml"  # новый файл для school

# GPIO настройка
GPIO.setmode(GPIO.BCM)
GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

last_pressed = 0

print("Ожидаю нажатия кнопки на GPIO", BUTTON_PIN)

def get_cameras_and_school():
    """Читает камеры и названия школ из конфигов"""
    cameras = []
    school_name = "Неизвестное учреждение"

    # читаем камеры из mediamtx
    if os.path.exists(MEDIAMTX_FILE):
        try:
            with open(MEDIAMTX_FILE, "r") as f:
                cfg = yaml.safe_load(f)
            cameras = list(cfg.get("paths", {}).keys())
        except Exception as e:
            print("Ошибка чтения медиа-конфига:", e)

    # читаем school из meta конфига
    if os.path.exists(META_CONFIG_FILE):
        try:
            with open(META_CONFIG_FILE, "r") as f:
                meta_cfg = yaml.safe_load(f)
            # если есть хотя бы одна камера, берем school первой
            for cam in cameras:
                school = meta_cfg.get("paths", {}).get(cam, {}).get("school")
                if school:
                    school_name = school
                    break
        except Exception as e:
            print("Ошибка чтения meta-конфига:", e)

    return cameras, school_name

try:
    while True:
        if GPIO.input(BUTTON_PIN) == GPIO.LOW:
            now = time.time()
            if now - last_pressed > DEBOUNCE_TIME:
                print("Кнопка нажата! Отправляю события...")

                cams, school_name = get_cameras_and_school()
                if not cams:
                    print("Камер не найдено.")
                else:
                    cam_param = ",".join(cams)
                    try:
                        # отправляем камеры и school
                        requests.post(f"http://{RPI_SERVER_IP}:5050/trigger?cam={cam_param}&school={school_name}", timeout=2)
                        requests.post(f"http://{RPI_SERVER_IP}:5000/siphone/call", timeout=2)
                        print(f"Отправляю POST на http://{RPI_SERVER_IP}:5050/trigger?cam={cam_param}&school={school_name}")
                        print("События отправлены для камер:", cam_param, "школа:", school_name)
                    except Exception as e:
                        print("Ошибка отправки:", e)

                last_pressed = now
            time.sleep(0.05)
        else:
            time.sleep(0.05)

except KeyboardInterrupt:
    print("Выход...")
finally:
    GPIO.cleanup()
