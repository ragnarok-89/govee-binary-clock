import os
import socket
import json
import base64
import time
import datetime
import requests

SETTINGS_FILE  = "settings.json"
settings_mtime = 0

def load_settings():
    global settings_mtime
    global DEVICE_IP, PANEL_COUNT, PUBLIC_IP, city_coords, weather_cache, weather_last_fetch
    global AM_PM, HOURS, MIN_TENS, MIN_ONES, SEC_TENS, SEC_ONES
    global COLOR_OFF, COLOR_AMPM_AM, COLOR_AMPM_PM, COLOR_HOUR, COLOR_MIN, COLOR_SEC
    global COLOR_TEMP_HOT, COLOR_TEMP_COLD, COLOR_HUMIDITY, COLOR_UV
    global BRIGHTNESS_MAX, BRIGHTNESS_NIGHT, DAYLIGHT_LEVEL_MAX
    global POWER_ON_TIME, POWER_OFF_TIME
    global WEATHER_REFRESH_INTERVAL, WEATHER_TRIGGER_SECONDS, WEATHER_DISPLAY_DURATION
    global FADE_STEPS, FADE_DURATION, FADE_TYPE, WEATHER_SECONDS

    with open(SETTINGS_FILE) as f:
        _cfg = json.load(f)

    DEVICE_IP   = _cfg["device"]["lan_ip"]
    PANEL_COUNT = _cfg["device"]["panel_count"]
    PUBLIC_IP   = _cfg["device"]["public_ip"]
    city_coords   = None
    weather_cache = None
    weather_last_fetch = 0

    AM_PM    = _cfg["panel_mappings"]["am_pm"]
    HOURS    = _cfg["panel_mappings"]["hours"]
    MIN_TENS = _cfg["panel_mappings"]["min_tens"]
    MIN_ONES = _cfg["panel_mappings"]["min_ones"]
    SEC_TENS = _cfg["panel_mappings"]["sec_tens"]
    SEC_ONES = _cfg["panel_mappings"]["sec_ones"]

    COLOR_OFF       = tuple(_cfg["colors"]["off"])
    COLOR_AMPM_AM   = tuple(_cfg["colors"]["ampm_am"])
    COLOR_AMPM_PM   = tuple(_cfg["colors"]["ampm_pm"])
    COLOR_HOUR      = tuple(_cfg["colors"]["hour"])
    COLOR_MIN       = tuple(_cfg["colors"]["min"])
    COLOR_SEC       = tuple(_cfg["colors"]["sec"])
    COLOR_TEMP_HOT  = tuple(_cfg["colors"]["temp_hot"])
    COLOR_TEMP_COLD = tuple(_cfg["colors"]["temp_cold"])
    COLOR_HUMIDITY  = tuple(_cfg["colors"]["humidity"])
    COLOR_UV        = tuple(_cfg["colors"]["uv"])

    BRIGHTNESS_MAX     = _cfg["brightness"]["max"]
    BRIGHTNESS_NIGHT   = _cfg["brightness"]["min"]
    DAYLIGHT_LEVEL_MAX = _cfg["brightness"]["daylight_max"]

    POWER_ON_TIME  = _cfg["power_schedule"]["power_on_time"]
    POWER_OFF_TIME = _cfg["power_schedule"]["power_off_time"]

    WEATHER_REFRESH_INTERVAL = _cfg["weather"]["refresh_interval"]
    WEATHER_TRIGGER_SECONDS  = _cfg["weather"]["trigger_seconds"]
    WEATHER_DISPLAY_DURATION = _cfg["weather"]["display_duration"]
    FADE_STEPS    = _cfg["fade"]["steps"]
    FADE_DURATION = _cfg["fade"]["duration"]
    FADE_TYPE     = _cfg["fade"]["type"]
    WEATHER_SECONDS = {
        (s + d) % 60
        for s in WEATHER_TRIGGER_SECONDS
        for d in range(WEATHER_DISPLAY_DURATION)
    }

    settings_mtime = os.path.getmtime(SETTINGS_FILE)


load_settings()


UDP_PORT = 4003
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def send_udp(message):
    sock.sendto(json.dumps(message).encode(), (DEVICE_IP, UDP_PORT))


def send_segment_color(colors):
    color_count = len(colors)
    data_size = 2 + color_count * 3
    byte_array = [0xBB, 0x00, data_size, 0xB0, 0, color_count]
    for r, g, b in colors:
        byte_array += [r, g, b]
    xor = 0
    for byte in byte_array:
        xor ^= byte
    byte_array.append(xor)
    pt = base64.b64encode(bytes(byte_array)).decode()
    send_udp({"msg": {"cmd": "razer", "data": {"pt": pt}}})


def razer_init():
    send_udp({"msg": {"cmd": "status", "data": {}}})
    send_udp({"msg": {"cmd": "razer", "data": {"pt": "uwABsQEK"}}})
    send_udp({"msg": {"cmd": "status", "data": {}}})


def razer_term():
    send_udp({"msg": {"cmd": "status", "data": {}}})
    send_udp({"msg": {"cmd": "razer", "data": {"pt": "uwABsQAL"}}})
    send_udp({"msg": {"cmd": "status", "data": {}}})


def get_coords():
    global city_coords
    if city_coords is not None:
        return city_coords
    try:
        url = f"http://ip-api.com/json/{PUBLIC_IP}" if PUBLIC_IP else "http://ip-api.com/json"
        resp = requests.get(url, timeout=5).json()
        if resp.get("status") != "success":
            raise Exception(resp.get("message", "unknown error"))
        city_coords = (resp["lat"], resp["lon"])
        print(f"Location resolved: {resp.get('city', '')}, {resp.get('country', '')} → {city_coords}")
    except Exception as e:
        print(f"Location lookup failed: {e}")
    return city_coords


def fetch_weather():
    global weather_cache, weather_last_fetch
    try:
        coords = get_coords()
        if coords is None:
            weather_last_fetch = time.time()
            return
        lat, lon = coords
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,uv_index,cloud_cover,shortwave_radiation"
            },
            timeout=5
        ).json()
        temp = round(resp["current"]["temperature_2m"])
        humidity = round(resp["current"]["relative_humidity_2m"])
        uv = round(resp["current"]["uv_index"])
        cloud = round(resp["current"]["cloud_cover"])
        daylight = round(resp["current"]["shortwave_radiation"])
        weather_cache = (temp, humidity, uv, cloud, daylight)
        weather_last_fetch = time.time()
        print(f"Weather updated: {humidity}% humidity, UV {uv}, {temp}°C, cloud cover {cloud}%, daylight {daylight} W/m²")
    except Exception as e:
        print(f"Weather fetch failed: {e}")


def get_weather():
    if weather_cache is None or (time.time() - weather_last_fetch) > WEATHER_REFRESH_INTERVAL:
        fetch_weather()
    return weather_cache


def set_bits(colors, panels, value, on_color):
    for i, panel in enumerate(panels):
        colors[panel] = on_color if (value >> i) & 1 else COLOR_OFF


def lerp_color(c1, c2, t):
    return tuple(round(a + (b - a) * t) for a, b in zip(c1, c2))


def fade_to(from_colors, to_colors):
    start = time.perf_counter()
    for step in range(1, FADE_STEPS + 1):
        t = step / FADE_STEPS
        blended = [lerp_color(a, b, t) for a, b in zip(from_colors, to_colors)]
        send_segment_color(blended)
        target = start + FADE_DURATION * step / FADE_STEPS
        remaining = target - time.perf_counter()
        if remaining > 0:
            time.sleep(remaining)


def fade_and_wait(from_colors, to_colors):
    fade_to(from_colors, to_colors)
    remaining = 1.0 - FADE_DURATION
    if remaining > 0:
        time.sleep(remaining)


def is_off_window():
    now = datetime.datetime.now().strftime("%H:%M")
    if POWER_OFF_TIME > POWER_ON_TIME:  # off window crosses midnight
        return now >= POWER_OFF_TIME or now < POWER_ON_TIME
    return POWER_OFF_TIME <= now < POWER_ON_TIME


def get_target_brightness(daylight=0):
    ratio = min(daylight / DAYLIGHT_LEVEL_MAX, 1.0)
    return round(BRIGHTNESS_NIGHT + (BRIGHTNESS_MAX - BRIGHTNESS_NIGHT) * ratio)


def build_clock_colors(now):
    hour12 = now.hour % 12 or 12
    is_pm = now.hour >= 12
    minute = now.minute
    second = now.second

    colors = [COLOR_OFF] * PANEL_COUNT

    for panel in AM_PM:
        colors[panel] = COLOR_AMPM_PM if is_pm else COLOR_AMPM_AM

    set_bits(colors, HOURS,    hour12,        COLOR_HOUR)
    set_bits(colors, MIN_TENS, minute // 10,  COLOR_MIN)
    set_bits(colors, MIN_ONES, minute % 10,   COLOR_MIN)
    set_bits(colors, SEC_TENS, second // 10,  COLOR_SEC)
    set_bits(colors, SEC_ONES, second % 10,   COLOR_SEC)

    return colors


def build_weather_colors(weather):
    colors = [COLOR_OFF] * PANEL_COUNT

    if weather is None:
        return colors

    temp, humidity, uv = weather[:3]
    temp_color = COLOR_TEMP_HOT if temp >= 0 else COLOR_TEMP_COLD
    abs_temp = abs(temp)

    set_bits(colors, HOURS,    humidity // 10, COLOR_HUMIDITY)
    set_bits(colors, MIN_TENS, humidity % 10,  COLOR_HUMIDITY)
    set_bits(colors, MIN_ONES, uv,             COLOR_UV)
    set_bits(colors, SEC_TENS, abs_temp // 10, temp_color)
    set_bits(colors, SEC_ONES, abs_temp % 10,  temp_color)

    return colors


try:
    print("Binary Clock Starting — Press Ctrl+C to quit")
    fetch_weather()

    device_on = not is_off_window()
    in_weather = False
    last_colors = [COLOR_OFF] * PANEL_COUNT
    current_brightness = -1

    if device_on:
        send_udp({"msg": {"cmd": "turn", "data": {"value": 1}}})
        time.sleep(1)
        razer_init()
        time.sleep(2)
        print("Device powered on.")
    else:
        send_udp({"msg": {"cmd": "turn", "data": {"value": 0}}})
        print(f"Starting in off window — device powered off until {POWER_ON_TIME}.")

    while True:
        if os.path.getmtime(SETTINGS_FILE) != settings_mtime:
            load_settings()
            current_brightness = -1
            print("Settings reloaded.")

        now = datetime.datetime.now()
        current_time = now.strftime("%H:%M")

        if device_on and current_time == POWER_OFF_TIME:
            print(f"Clock off time ({POWER_OFF_TIME}) reached — powering off.")
            razer_term()
            send_udp({"msg": {"cmd": "turn", "data": {"value": 0}}})
            device_on = False

        elif not device_on and current_time == POWER_ON_TIME:
            print(f"Clock on time ({POWER_ON_TIME}) reached — powering on.")
            send_udp({"msg": {"cmd": "turn", "data": {"value": 1}}})
            time.sleep(1)
            razer_init()
            time.sleep(2)
            device_on = True
            in_weather = False
            last_colors = [COLOR_OFF] * PANEL_COUNT
            current_brightness = -1
            target = build_clock_colors(now)
            fade_to(last_colors, target)
            last_colors = target

        if not device_on:
            on_h, on_m = map(int, POWER_ON_TIME.split(":"))
            wake = now.replace(hour=on_h, minute=on_m, second=0, microsecond=0)
            if wake <= now:
                wake += datetime.timedelta(days=1)
            time.sleep((wake - now).total_seconds())
            continue

        should_weather = now.second in WEATHER_SECONDS

        weather = get_weather()
        daylight = weather[4] if weather else 0
        brightness = get_target_brightness(daylight)
        if brightness != current_brightness:
            send_udp({"msg": {"cmd": "brightness", "data": {"value": brightness}}})
            current_brightness = brightness
            print(f"Brightness set to {brightness}")

        if should_weather != in_weather:
            target = build_weather_colors(weather) if should_weather else build_clock_colors(now)
            fade_and_wait(last_colors, target)
            last_colors = target
            in_weather = should_weather
        else:
            target = build_weather_colors(weather) if in_weather else build_clock_colors(now)
            if not in_weather and FADE_TYPE == "transition":
                fade_and_wait(last_colors, target)
            else:
                send_segment_color(target)
                time.sleep(1)
            last_colors = target

except KeyboardInterrupt:
    print("\nShutting down...")
    razer_term()
    send_udp({"msg": {"cmd": "turn", "data": {"value": 0}}})
    sock.close()
