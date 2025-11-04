import os
import yaml
import subprocess
import logging
from flask import Flask, request, render_template, redirect
from flask_socketio import SocketIO
import requests
import netifaces

logging.basicConfig(level=logging.INFO)
CONFIG = "/etc/mediamtx.yml"
META_CONFIG = "/home/pi/camportal/cameras_meta.yml"
# ---------- RTSP шаблоны ----------
CAM_TEMPLATES = {
    "dahua":      "rtsp://{user}:{pwd}@{ip}:554/cam/realmonitor?channel=1&subtype=1",
    "hikvision":  "rtsp://{user}:{pwd}@{ip}:554/Streaming/Channels/101",
    "hikvision_sub": "rtsp://{user}:{pwd}@{ip}:554/Streaming/Channels/102",
    "ezviz":      "rtsp://{user}:{pwd}@{ip}:554/h264_stream",
    "xm":         "rtsp://{user}:{pwd}@{ip}:554/user={user}_password={pwd}_channel=1_stream=0.sdp",
    "onvif":      "rtsp://{user}:{pwd}@{ip}:554/onvif1",
    "generic":    "rtsp://{user}:{pwd}@{ip}:554/live.sdp",
    "axis":       "rtsp://{user}:{pwd}@{ip}/axis-media/media.amp",
    "amcrest":    "rtsp://{user}:{pwd}@{ip}:554/cam/realmonitor?channel=1&subtype=0",
    "reolink":    "rtsp://{user}:{pwd}@{ip}:554/h264Preview_01_main",
    "foscam":     "rtsp://{user}:{pwd}@{ip}:554/videoMain",
    "bosch":      "rtsp://{user}:{pwd}@{ip}:554/rtsp_tunnel",
    "uniview":    "rtsp://{user}:{pwd}@{ip}:554/live/main",
    "uniview_sub":"rtsp://{user}:{pwd}@{ip}:554/live/sub",
    "annke":      "rtsp://{user}:{pwd}@{ip}:554/Streaming/Channels/101",
    "wisenet":    "rtsp://{user}:{pwd}@{ip}:554/profile2/media.smp",
    "tp-link":    "rtsp://{user}:{pwd}@{ip}:554/stream1",
    "vivotek":    "rtsp://{user}:{pwd}@{ip}:554/live.sdp",
    "arlo":       "rtsp://{user}:{pwd}@{ip}:554/live",
    "wyze":       "rtsp://{user}:{pwd}@{ip}:554/live",
}

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

# --- маршруты ---
@app.route("/")
def index():
    cfg = {}
    if os.path.exists(CONFIG):
        with open(CONFIG) as f:
            cfg = yaml.safe_load(f) or {}
    paths = cfg.get("paths", {})

    school = ""
    if os.path.exists(META_CONFIG):
        with open(META_CONFIG) as f:
            meta_cfg = yaml.safe_load(f) or {}
            # берём общее school для всех
            school = meta_cfg.get("school", "")

    return render_template("index.html", paths=paths, brands=CAM_TEMPLATES.keys(), school=school)

@app.route("/set_server_ip", methods=["POST"])
def set_server_ip():
    server_ip = request.form.get("server_ip", "").strip()
    if not server_ip:
        return "Не указан IP сервера", 400

    meta_cfg = {}
    if os.path.exists(META_CONFIG):
        with open(META_CONFIG) as f:
            meta_cfg = yaml.safe_load(f) or {}

    # Сохраняем IP сервера
    meta_cfg["server_ip"] = server_ip

    with open(META_CONFIG, "w") as f:
        yaml.safe_dump(meta_cfg, f)

    logging.info(f"Обновлен IP сервера: {server_ip}")
    return redirect("/")

@app.route("/delete_camera", methods=["POST"])
def delete_camera():
    name = request.form.get("name", "").strip()
    if not name:
        return "Не указано имя камеры", 400

    # Удаляем из основного медиа-конфига
    cfg = {}
    if os.path.exists(CONFIG):
        with open(CONFIG) as f:
            cfg = yaml.safe_load(f) or {}
    if "paths" in cfg and name in cfg["paths"]:
        del cfg["paths"][name]
        with open(CONFIG, "w") as f:
            yaml.safe_dump(cfg, f)
        subprocess.run(["sudo", "systemctl", "restart", "mediamtx"], check=False)
        app.logger.info(f"Камера '{name}' удалена из основного конфига")
    return redirect("/")

@app.route("/set_school", methods=["POST"])
def set_school():
    school = request.form.get("school", "").strip()
    if not school:
        return "Не указана школа", 400

    meta_cfg = {}
    if os.path.exists(META_CONFIG):
        with open(META_CONFIG) as f:
            meta_cfg = yaml.safe_load(f) or {}

    # сохраняем одно значение для всей системы
    meta_cfg["school"] = school

    with open(META_CONFIG, "w") as f:
        yaml.safe_dump(meta_cfg, f)

    logging.info(f"Обновлена школа: {school}")
    return redirect("/")

@app.route("/add", methods=["POST"])
def add():
    name     = request.form.get("name", "").strip()
    brand    = request.form.get("brand", "").strip().lower()
    ip       = request.form.get("ip", "").strip()
    user     = request.form.get("user", "").strip()
    password = request.form.get("password", "").strip()

    if not all([name, brand, ip, user]):
        return "Не все обязательные поля заполнены", 400
    if brand not in CAM_TEMPLATES:
        return f"Неизвестный бренд {brand}", 400

    url = CAM_TEMPLATES[brand].format(user=user, pwd=password, ip=ip)

    # обновляем медиа конфиг (только source)
    cfg = {}
    if os.path.exists(CONFIG):
        with open(CONFIG) as f:
            cfg = yaml.safe_load(f) or {}
    cfg.setdefault("paths", {})[name] = {"source": url}
    with open(CONFIG, "w") as f:
        yaml.safe_dump(cfg, f)

    subprocess.run(["sudo", "systemctl", "restart", "mediamtx"], check=False)
    logging.info(f"Added camera '{name}' -> {url}")
    return redirect("/")

@app.route("/trigger", methods=["POST"])
def trigger():
    # читаем JSON из тела запроса
    data = request.get_json(silent=True) or {}

    # читаем из JSON или query string
    cams = data.get("cams")
    if not cams:
        cam_param = request.args.get("cam", "")
        cams = [c.strip() for c in cam_param.split(",") if c.strip()]

    if not cams:
        return "No cameras specified", 400

    # получаем название школы
    school = data.get("school", "")
    if not school and os.path.exists(META_CONFIG):
        with open(META_CONFIG) as f:
            meta_cfg = yaml.safe_load(f) or {}
            school = meta_cfg.get("school", "")

    # получаем IP сервера
    server_ip = ""
    if os.path.exists(META_CONFIG):
        with open(META_CONFIG) as f:
            meta_cfg = yaml.safe_load(f) or {}
            server_ip = meta_cfg.get("server_ip", "")

    if not server_ip:
        return "Server IP not set", 400

    # получаем IP интерфейса wg0
    wg0_ip = ""
    try:
        import netifaces
        if "wg0" in netifaces.interfaces():
            addrs = netifaces.ifaddresses("wg0")
            if netifaces.AF_INET in addrs:
                wg0_ip = addrs[netifaces.AF_INET][0]["addr"]
    except Exception as e:
        app.logger.warning(f"Can't get wg0 IP: {e}")

    # формируем объект для отправки на сервер
    payload = {
        "cams": cams,
        "school": school,
        "wg0_ip": wg0_ip
    }
    app.logger.info(f"Sending trigger to server {server_ip}: {payload}")

    # отправляем POST на центральный сервер
    try:
        import requests
        r = requests.post(f"http://{server_ip}:5050/trigger", json=payload, timeout=5)
        if r.status_code != 200:
            app.logger.warning(f"Server returned {r.status_code}: {r.text}")
            return f"Failed to send trigger: {r.status_code}", 500
    except Exception as e:
        app.logger.error(f"Error sending trigger: {e}")
        return f"Error sending trigger: {e}", 500

    return "ok"

# --- запуск ---
if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5050)

