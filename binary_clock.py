import socket
import json
import base64
import time
import datetime
import requests

#Govee device settings
DEVICE_IP = "192.168.1.14"
PANEL_COUNT = 20
COUNTRY = "CA" #Country codes: https://en.wikipedia.org/wiki/ISO_3166-1_alpha-2#Officially_assigned_code_elements
CITY    = "Montreal"
UDP_PORT = 4003

#Panel mappings - index 0 = LSB (bit 0), last index = MSB
AM_PM    = [0, 9]
HOURS    = [15, 14, 1, 2]
MIN_TENS = [16, 13, 3]
MIN_ONES = [17, 12, 4, 5]
SEC_TENS = [18, 11, 6]
SEC_ONES = [19, 10, 8, 7]

#Color definitions (R, G, B)
COLOR_OFF       = (0,   0,   0)   #none/off
COLOR_AMPM_AM   = (255, 180,  0)  #amber
COLOR_AMPM_PM   = (120,   0, 255) #purple
COLOR_HOUR      = (255,  30,   0) #orange-red
COLOR_MIN       = (0,  200,   0)  #green
COLOR_SEC       = (0,   80, 255)  #blue
COLOR_TEMP_HOT  = (255,  30,   0) #orange-red
COLOR_TEMP_COLD = (0,   80, 255)  #blue
COLOR_HUMIDITY  = (100, 200, 255) #light blue
COLOR_UV        = (180,   0, 255) #violet

#Brightness settings
BRIGHTNESS_DAY   = 100      #brightness during the day (0-100)
BRIGHTNESS_NIGHT = 10       #brightness at night (0-100)
NIGHT_START_TIME = "22:00"  #time when night mode begins (HH:MM, 24hr)
NIGHT_END_TIME   = "06:00"  #time when night mode ends (HH:MM, 24hr)

#Power schedule
POWER_ON_TIME    = "06:00"  #time to power on the device (HH:MM, 24hr)
POWER_OFF_TIME   = "23:00"  #time to power off the device (HH:MM, 24hr)

#Weather Display Settings
WEATHER_REFRESH_INTERVAL = 300  #re-fetch every 5 minutes
WEATHER_TRIGGER_SECONDS  = [30] #seconds at which weather display starts; can include multiple values e.g. [0, 30] to show on both minute and half-minute
WEATHER_DISPLAY_DURATION = 3    #how many seconds to show weather
WEATHER_SECONDS = {
    (s + d) % 60
    for s in WEATHER_TRIGGER_SECONDS
    for d in range(WEATHER_DISPLAY_DURATION)
}
FADE_STEPS    = 15   #number of frames in the transition
FADE_DURATION = 0.6  #total seconds the fade takes


sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
weather_cache = None
weather_last_fetch = 0
city_coords = None


def send_udp(message):
    sock.sendto(bytes(json.dumps(message), "utf-8"), (DEVICE_IP, UDP_PORT))


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


def get_city_coords():
    global city_coords
    if city_coords is not None:
        return city_coords
    resp = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": CITY, "count": 1, "language": "en", "format": "json"},
        timeout=5
    ).json()
    result = resp["results"][0]
    city_coords = (result["latitude"], result["longitude"])
    print(f"Location resolved: {result['name']}, {result.get('country', '')} → {city_coords}")
    return city_coords


def fetch_weather():
    global weather_cache, weather_last_fetch
    try:
        lat, lon = get_city_coords()
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,uv_index,cloud_cover"
            },
            timeout=5
        ).json()
        temp = round(resp["current"]["temperature_2m"])
        humidity = round(resp["current"]["relative_humidity_2m"])
        uv = round(resp["current"]["uv_index"])
        cloud = round(resp["current"]["cloud_cover"])
        weather_cache = (temp, humidity, uv, cloud)
        weather_last_fetch = time.time()
        print(f"Weather updated: {humidity}% humidity, UV {uv}, {temp}°C, cloud cover {cloud}%")
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
    return tuple(round(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def fade_to(from_colors, to_colors):
    start = time.perf_counter()
    for step in range(1, FADE_STEPS + 1):
        t = step / FADE_STEPS
        blended = [lerp_color(from_colors[i], to_colors[i], t) for i in range(PANEL_COUNT)]
        send_segment_color(blended)
        target = start + FADE_DURATION * step / FADE_STEPS
        remaining = target - time.perf_counter()
        if remaining > 0:
            time.sleep(remaining)


def is_off_window():
    now = datetime.datetime.now().strftime("%H:%M")
    if POWER_OFF_TIME > POWER_ON_TIME:  # off window crosses midnight
        return now >= POWER_OFF_TIME or now < POWER_ON_TIME
    return POWER_OFF_TIME <= now < POWER_ON_TIME


def get_target_brightness(cloud=0):
    now = datetime.datetime.now().strftime("%H:%M")
    if NIGHT_START_TIME > NIGHT_END_TIME:  # night window crosses midnight
        in_night = now >= NIGHT_START_TIME or now < NIGHT_END_TIME
    else:
        in_night = NIGHT_START_TIME <= now < NIGHT_END_TIME
    if in_night:
        return BRIGHTNESS_NIGHT
    return round(BRIGHTNESS_DAY - (BRIGHTNESS_DAY - BRIGHTNESS_NIGHT) * cloud / 100)


def build_clock_colors():
    now = datetime.datetime.now()
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


def build_weather_colors():
    weather = get_weather()
    colors = [COLOR_OFF] * PANEL_COUNT

    if weather is None:
        return colors

    temp, humidity, uv, cloud = weather
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
            target = build_clock_colors()
            fade_to(last_colors, target)
            last_colors = target

        if not device_on:
            now_dt = datetime.datetime.now()
            on_h, on_m = map(int, POWER_ON_TIME.split(":"))
            wake = now_dt.replace(hour=on_h, minute=on_m, second=0, microsecond=0)
            if wake <= now_dt:
                wake += datetime.timedelta(days=1)
            time.sleep((wake - now_dt).total_seconds())
            continue

        should_weather = now.second in WEATHER_SECONDS

        weather = get_weather()
        cloud = weather[3] if weather else 0
        brightness = get_target_brightness(cloud)
        if brightness != current_brightness:
            send_udp({"msg": {"cmd": "brightness", "data": {"value": brightness}}})
            current_brightness = brightness
            print(f"Brightness set to {brightness}")

        if should_weather != in_weather:
            target = build_weather_colors() if should_weather else build_clock_colors()
            fade_to(last_colors, target)
            last_colors = target
            in_weather = should_weather
            remaining = 1.0 - FADE_DURATION
            if remaining > 0:
                time.sleep(remaining)
        else:
            last_colors = build_weather_colors() if in_weather else build_clock_colors()
            send_segment_color(last_colors)
            time.sleep(1)

except KeyboardInterrupt:
    print("\nShutting down...")
    razer_term()
    send_udp({"msg": {"cmd": "turn", "data": {"value": 0}}})
    sock.close()
