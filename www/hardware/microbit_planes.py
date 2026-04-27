"""
✈️ Planes in the Sky — micro:bit Companion
Upload this to your BBC micro:bit via python.microbit.org

FEATURES:
- LED radar: 5x5 grid shows nearby planes as dots
- Overhead alert: buzzer + animation when plane is <8km
- Compass pointer: tilt micro:bit to point at nearest plane
- Button A: cycle display modes (radar / count / compass / country)
- Button B: cycle through planes (show callsign scroll)
- Shake: refresh data request

PROTOCOL (serial/BLE UART, newline-delimited JSON):
  {"t":"update","n":12,"planes":[{"cs":"AFR123","d":45,"b":210,"a":10000,"c":"FR"},...]}
  {"t":"alert","cs":"BAW456","d":5.2,"a":8500,"c":"GB"}
  {"t":"clear"}
"""

from microbit import *
import music

# ========== State ==========
planes = []        # list of {cs, d, b, a, c} dicts
plane_count = 0
display_mode = 0   # 0=radar, 1=count, 2=compass, 3=country
selected_idx = 0
nearest = None
last_update = 0
alert_active = False

# ========== LED Patterns ==========
PLANE_ICON = Image("00900:09990:99999:09090:00000")
PLANE_ICON2 = Image("00900:09990:09090:00000:00000")
ALERT_FRAMES = [
    Image("00000:00000:00900:00000:00000"),
    Image("00000:00900:09090:00900:00000"),
    Image("00900:09090:90009:09090:00900"),
    Image("09090:90009:00000:90009:09090"),
    Image("90009:00000:00000:00000:90009"),
]

# Country flag pixel art (2x3 on 5x5 grid, centered)
FLAGS = {
    "FR": Image("00900:00900:09990:09990:00900"),  # tricolor hint
    "GB": Image("90909:09990:99999:09990:90909"),  # union cross
    "US": Image("99900:99900:00000:90909:09090"),  # stars & stripes
    "DE": Image("00000:99999:99999:09090:00000"),
    "AE": Image("90000:99999:99999:99999:00000"),
    "TR": Image("00000:09900:09990:09900:00000"),  # crescent hint
}

# ========== Helpers ==========
def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def bearing_to_xy(bearing, dist_norm):
    """Convert bearing (degrees) + normalized distance to 5x5 grid position."""
    import math
    rad = math.radians(bearing)
    # bearing: 0=N=up, 90=E=right, etc.
    x = math.sin(rad) * dist_norm
    y = -math.cos(rad) * dist_norm
    gx = clamp(int(2 + x * 2.4), 0, 4)
    gy = clamp(int(2 + y * 2.4), 0, 4)
    return gx, gy

def alt_to_brightness(alt):
    """Map altitude to LED brightness 1-9."""
    if alt < 2000:
        return 2
    elif alt < 5000:
        return 4
    elif alt < 8000:
        return 6
    elif alt < 11000:
        return 8
    return 9

# ========== Display Modes ==========
def show_radar():
    """Mode 0: 5x5 radar grid. Center=you, dots=planes."""
    img = Image("00000:" * 5)
    # Center blip (you)
    img.set_pixel(2, 2, 3)

    max_dist = 200  # km
    for p in planes:
        d = p.get("d", 999)
        b = p.get("b", 0)
        a = p.get("a", 5000)
        if d > max_dist:
            continue
        dist_norm = min(1.0, d / max_dist)
        gx, gy = bearing_to_xy(b, dist_norm)
        brightness = alt_to_brightness(a)
        # Don't overwrite center
        if gx == 2 and gy == 2:
            gy = 1
        current = img.get_pixel(gx, gy)
        img.set_pixel(gx, gy, max(current, brightness))

    display.show(img)

def show_count():
    """Mode 1: Big number showing plane count."""
    if plane_count <= 9:
        display.show(str(plane_count))
    elif plane_count <= 99:
        display.scroll(str(plane_count), delay=80, wait=False)
    else:
        display.scroll(str(plane_count), delay=60, wait=False)

def show_compass():
    """Mode 2: Arrow pointing at nearest plane using accelerometer + bearing."""
    if not nearest:
        display.show(Image.SAD)
        return

    target_bearing = nearest.get("b", 0)

    # Get micro:bit's heading from compass
    try:
        my_heading = compass.heading()
    except:
        my_heading = 0

    # Relative angle to target
    rel = (target_bearing - my_heading) % 360

    # Map to 8 directions
    arrows = [
        Image.ARROW_N, Image.ARROW_NE, Image.ARROW_E, Image.ARROW_SE,
        Image.ARROW_S, Image.ARROW_SW, Image.ARROW_W, Image.ARROW_NW
    ]
    idx = int((rel + 22.5) / 45) % 8
    display.show(arrows[idx])

def show_country():
    """Mode 3: Show flag of nearest plane's country."""
    if not nearest:
        display.show("?")
        return
    c = nearest.get("c", "")
    if c in FLAGS:
        display.show(FLAGS[c])
    else:
        # Scroll country code
        display.scroll(c if c else "?", delay=100, wait=False)

# ========== Alerts ==========
def overhead_alert(plane):
    """Visual + audio alert when plane is very close."""
    global alert_active
    alert_active = True

    # Expanding ring animation
    for frame in ALERT_FRAMES:
        display.show(frame)
        sleep(80)

    # Show plane icon
    display.show(PLANE_ICON)
    music.play(["C5:2", "E5:2", "G5:4"], wait=False)
    sleep(400)
    display.show(PLANE_ICON2)
    sleep(300)

    # Scroll callsign
    cs = plane.get("cs", "???")
    d = plane.get("d", 0)
    display.scroll("{} {}km".format(cs, int(d)), delay=70)

    alert_active = False

# ========== Data Parsing ==========
def parse_message(msg):
    """Parse JSON-like message from serial. Simplified parser for micro:bit."""
    global planes, plane_count, nearest

    msg = msg.strip()
    if not msg:
        return

    # Simple protocol: lines starting with specific prefixes
    # Format: U|count|cs1,d1,b1,a1,c1|cs2,d2,b2,a2,c2|...
    # Alert: A|cs|d|a|c
    # Clear: C

    parts = msg.split("|")
    cmd = parts[0] if parts else ""

    if cmd == "U" and len(parts) >= 2:
        # Update
        try:
            plane_count = int(parts[1])
        except:
            plane_count = 0

        planes = []
        for i in range(2, len(parts)):
            fields = parts[i].split(",")
            if len(fields) >= 5:
                try:
                    planes.append({
                        "cs": fields[0],
                        "d": float(fields[1]),
                        "b": float(fields[2]),
                        "a": float(fields[3]),
                        "c": fields[4]
                    })
                except:
                    pass

        # Find nearest
        nearest = None
        min_d = 9999
        for p in planes:
            if p["d"] < min_d:
                min_d = p["d"]
                nearest = p

    elif cmd == "A" and len(parts) >= 5:
        # Proximity alert
        try:
            alert_plane = {
                "cs": parts[1],
                "d": float(parts[2]),
                "a": float(parts[3]),
                "c": parts[4]
            }
            overhead_alert(alert_plane)
        except:
            pass

    elif cmd == "C":
        planes = []
        plane_count = 0
        nearest = None

# ========== Startup ==========
display.scroll("SKY", delay=60)
display.show(PLANE_ICON)
sleep(800)

# Calibrate compass
if not compass.is_calibrated():
    display.scroll("TILT", delay=60)
    compass.calibrate()

display.clear()

# ========== Main Loop ==========
buf = ""

while True:
    # Check serial for data
    if uart.any():
        try:
            data = uart.read()
            if data:
                buf += str(data, 'utf-8')
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    parse_message(line)
        except:
            buf = ""

    # Button A: cycle display mode
    if button_a.was_pressed():
        display_mode = (display_mode + 1) % 4
        labels = ["RADAR", "COUNT", "POINT", "FLAG"]
        display.scroll(labels[display_mode], delay=50, wait=False)
        sleep(600)

    # Button B: cycle through planes, scroll callsign
    if button_b.was_pressed():
        if planes:
            selected_idx = (selected_idx + 1) % len(planes)
            p = planes[selected_idx]
            display.scroll("{} {}km".format(p["cs"], int(p["d"])), delay=60, wait=False)

    # Shake: request refresh
    if accelerometer.was_gesture("shake"):
        uart.write("REFRESH\n")
        display.show(Image.ARROW_N)
        sleep(200)

    # Update display based on mode (if not in alert)
    if not alert_active:
        if display_mode == 0:
            show_radar()
        elif display_mode == 1:
            show_count()
        elif display_mode == 2:
            show_compass()
        elif display_mode == 3:
            show_country()

    sleep(100)
